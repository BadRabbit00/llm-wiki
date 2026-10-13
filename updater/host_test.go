package main

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

// recordingRunner answers each program from a script and remembers every command line.
type recordingRunner struct {
	calls  [][]string
	output map[string]string // by program base name
	err    map[string]error
	onRun  func(args []string)
}

func (r *recordingRunner) Run(_ context.Context, name string, args ...string) ([]byte, error) {
	r.calls = append(r.calls, append([]string{name}, args...))
	if r.onRun != nil {
		r.onRun(args)
	}
	base := filepath.Base(name)
	return []byte(r.output[base]), r.err[base]
}

func newSystem(t *testing.T, runner *recordingRunner) *System {
	t.Helper()
	return &System{
		cfg: Config{
			Repository: repository, Identity: "https://github.com/BadRabbit00/llm-wiki/.github/workflows/release.yml@refs/tags/",
			Issuer: "https://token.actions.githubusercontent.com", Root: t.TempDir(),
			Skopeo: "skopeo", Cosign: "cosign", Podman: "/usr/bin/podman", Systemctl: "/usr/bin/systemctl",
			Tar: "/usr/bin/tar", RunScript: "/opt/llm-wiki/current/bin/llm-wiki-run",
		},
		run:  runner,
		http: http.DefaultClient,
	}
}

func TestRegistryQueries(t *testing.T) {
	runner := &recordingRunner{output: map[string]string{
		"skopeo": `{"Repository":"ghcr.io/badrabbit00/llm-wiki","Tags":["main","v1.0.0"],
			"Digest":"` + digest("b") + `","Labels":{"org.opencontainers.image.revision":"bbbbbbb"}}`,
	}}
	system := newSystem(t, runner)
	tags, err := system.Tags(context.Background())
	if err != nil || !slices.Equal(tags, []string{"main", "v1.0.0"}) {
		t.Fatalf("tags %v, %v", tags, err)
	}
	image, err := system.Inspect(context.Background(), "v1.0.0")
	if err != nil || image != (Image{Tag: "v1.0.0", Digest: digest("b"), Revision: "bbbbbbb"}) {
		t.Fatalf("image %+v, %v", image, err)
	}
	want := [][]string{
		{"skopeo", "list-tags", "docker://" + repository},
		{"skopeo", "inspect", "docker://" + repository + ":v1.0.0"},
	}
	if !slices.EqualFunc(runner.calls, want, slices.Equal) {
		t.Fatalf("calls %v", runner.calls)
	}
	runner.output["skopeo"] = `{"Digest":"sha512:abc"}`
	if _, err := system.Inspect(context.Background(), "v1.0.0"); err == nil {
		t.Fatal("a digest the pin cannot hold was accepted")
	}
}

func TestVerifyBindsTheSignatureToThisTagAndWorkflow(t *testing.T) {
	runner := &recordingRunner{}
	if err := newSystem(t, runner).Verify(context.Background(), "v1.1.0", digest("b")); err != nil {
		t.Fatal(err)
	}
	want := []string{"cosign", "verify-attestation", "--type", "https://slsa.dev/provenance/v1",
		"--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
		"--certificate-identity", "https://github.com/BadRabbit00/llm-wiki/.github/workflows/release.yml@refs/tags/v1.1.0",
		repository + "@" + digest("b")}
	if !slices.Equal(runner.calls[0], want) {
		t.Fatalf("cosign %v", runner.calls[0])
	}
}

func TestContainerAndUnitCommands(t *testing.T) {
	runner := &recordingRunner{output: map[string]string{
		"llm-wiki-run": `[{"id":"j1","kind":"ingest_book","status":"paused","updated_at":"2026-10-13"}]`,
		"systemctl":    "activating\n",
	}, err: map[string]error{"systemctl": errors.New("exit status 3")}}
	system := newSystem(t, runner)
	ctx := context.Background()
	if err := system.Pull(ctx, digest("b")); err != nil {
		t.Fatal(err)
	}
	jobs, err := system.Jobs(ctx)
	if err != nil || len(jobs) != 1 || jobs[0] != (Job{ID: "j1", Kind: "ingest_book", Status: "paused", UpdatedAt: "2026-10-13"}) {
		t.Fatalf("jobs %+v, %v", jobs, err)
	}
	if state := system.UnitState(ctx, unitBackup); state != "activating" {
		t.Fatalf("a non-zero exit hid the unit state: %q", state)
	}
	if err := system.Maintenance(ctx, "wikisvc", "lint"); err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"/usr/bin/podman", "pull", "--quiet", repository + "@" + digest("b")},
		{"/opt/llm-wiki/current/bin/llm-wiki-run", "once", "maintenance", "wikiagent", "jobs"},
		{"/usr/bin/systemctl", "is-active", unitBackup},
		{"/opt/llm-wiki/current/bin/llm-wiki-run", "once", "maintenance", "wikisvc", "lint"},
	}
	if !slices.EqualFunc(runner.calls, want, slices.Equal) {
		t.Fatalf("calls %v", runner.calls)
	}
}

func TestArchiveIsPrivateAndNeverLeftHalfWritten(t *testing.T) {
	runner := &recordingRunner{err: map[string]error{}}
	system := newSystem(t, runner)
	path := filepath.Join(t.TempDir(), "backups", "pre-update.tar.gz")
	runner.onRun = func(args []string) { _ = os.WriteFile(path, []byte("archive"), 0o644) }
	if err := system.Archive(context.Background(), path); err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(runner.calls[0], append([]string{"/usr/bin/tar", "-C", system.cfg.Root, "-czf", path}, archived...)) {
		t.Fatalf("tar %v", runner.calls[0])
	}
	info, _ := os.Stat(path)
	directory, _ := os.Stat(filepath.Dir(path))
	if info.Mode().Perm() != 0o600 || directory.Mode().Perm() != 0o700 {
		t.Fatalf("archive %v, directory %v", info.Mode(), directory.Mode())
	}
	runner.err["tar"] = errors.New("no space left on device")
	if err := system.Archive(context.Background(), path); err == nil {
		t.Fatal("a failed tar passed")
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("a half-written archive was left where a backup is expected")
	}
}

func TestRestoreKeepsTheFailedDataAside(t *testing.T) {
	runner := &recordingRunner{}
	system := newSystem(t, runner)
	for _, relative := range []string{"var/lib/llm-wiki/wiki", "etc/llm-wiki"} {
		if err := os.MkdirAll(filepath.Join(system.cfg.Root, relative), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if err := system.Restore(context.Background(), "/backups/pre-update.tar.gz", "20261013T120000Z"); err != nil {
		t.Fatal(err)
	}
	for _, relative := range []string{"var/lib/llm-wiki/wiki", "etc/llm-wiki"} {
		if _, err := os.Stat(filepath.Join(system.cfg.Root, relative+".failed-20261013T120000Z")); err != nil {
			t.Fatalf("%s not kept aside: %v", relative, err)
		}
	}
	if !slices.Equal(runner.calls[0], []string{"/usr/bin/tar", "-C", system.cfg.Root, "-xzf", "/backups/pre-update.tar.gz"}) {
		t.Fatalf("tar %v", runner.calls[0])
	}
}

func TestHealthEndpoints(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v1/health":
			_, _ = w.Write([]byte(`{"status":"ok","version":"1.1.0","index_commit":"x"}`))
		case "/healthz":
			_, _ = w.Write([]byte(`{"status":"ok"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	system := newSystem(t, &recordingRunner{})
	system.cfg.WikiURL, system.cfg.UIURL = server.URL, server.URL
	if version, err := system.WikiVersion(context.Background()); err != nil || version != "1.1.0" {
		t.Fatalf("version %q, %v", version, err)
	}
	if !system.UIHealthy(context.Background()) {
		t.Fatal("wiki-ui reported unhealthy")
	}
	system.cfg.WikiURL = server.URL + "/missing"
	if _, err := system.WikiVersion(context.Background()); err == nil || !strings.Contains(err.Error(), "404") {
		t.Fatalf("an error page counted as health: %v", err)
	}
}
