package main

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"
)

const repository = "ghcr.io/badrabbit00/llm-wiki"

func digest(c string) string { return "sha256:" + strings.Repeat(c, 64) }

// fakeHost behaves like the machine: units change state on stop and start, wikisvc
// reports the version of the pinned image, and Restore puts the previous pin back
// as unpacking the real archive does.
type fakeHost struct {
	mu        sync.Mutex
	imageFile string
	calls     []string
	tags      []string
	images    map[string]Image  // by tag
	versions  map[string]string // by digest: what /api/v1/health reports
	units     map[string]string
	fail      map[string]error // by call name
	badSig    map[string]bool  // by tag
	noStart   map[string]bool  // units that never become active
	jobs      []Job
}

func newFakeHost(imageFile string) *fakeHost {
	return &fakeHost{
		imageFile: imageFile,
		tags:      []string{"main", "v1.0.0", "v1.1.0", "v1.2.0-beta.1"},
		images: map[string]Image{
			"v1.0.0":        {Tag: "v1.0.0", Digest: digest("a"), Revision: "aaaaaaa"},
			"v1.1.0":        {Tag: "v1.1.0", Digest: digest("b"), Revision: "bbbbbbb"},
			"v1.2.0-beta.1": {Tag: "v1.2.0-beta.1", Digest: digest("c"), Revision: "ccccccc"},
		},
		versions: map[string]string{digest("a"): "1.0.0", digest("b"): "1.1.0", digest("c"): "1.2.0"},
		units: map[string]string{
			unitWiki: "active", unitAgent: "active", unitUI: "active", timerBackup: "active", unitBackup: "inactive",
		},
		fail:    map[string]error{},
		badSig:  map[string]bool{},
		noStart: map[string]bool{},
		jobs:    []Job{{ID: "j1", Kind: "ingest_book", Status: "running"}},
	}
}

func (h *fakeHost) call(name string) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.calls = append(h.calls, name)
	return h.fail[name]
}

func (h *fakeHost) Calls() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return slices.Clone(h.calls)
}

func (h *fakeHost) Tags(context.Context) ([]string, error) { return h.tags, h.call("tags") }
func (h *fakeHost) Inspect(_ context.Context, tag string) (Image, error) {
	return h.images[tag], h.call("inspect " + tag)
}
func (h *fakeHost) Verify(_ context.Context, tag, _ string) error {
	if err := h.call("verify " + tag); err != nil {
		return err
	}
	if h.badSig[tag] {
		return errors.New("no matching attestation")
	}
	return nil
}
func (h *fakeHost) Pull(_ context.Context, d string) error { return h.call("pull " + d[7:8]) }
func (h *fakeHost) Jobs(context.Context) ([]Job, error)    { return h.jobs, h.call("jobs") }
func (h *fakeHost) Systemctl(_ context.Context, args ...string) error {
	if err := h.call("systemctl " + strings.Join(args, " ")); err != nil {
		return err
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	state := map[string]string{"stop": "inactive", "start": "active"}[args[0]]
	for _, unit := range args[1:] {
		if unit != "--no-block" && !h.noStart[unit] {
			h.units[unit] = state
		}
	}
	return nil
}
func (h *fakeHost) UnitState(_ context.Context, unit string) string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.units[unit]
}
func (h *fakeHost) Maintenance(_ context.Context, args ...string) error {
	return h.call("maintenance " + strings.Join(args, " "))
}
func (h *fakeHost) Archive(_ context.Context, path string) error {
	return h.call("archive " + filepath.Base(path))
}
func (h *fakeHost) Restore(_ context.Context, path, _ string) error {
	if err := h.call("restore " + filepath.Base(path)); err != nil {
		return err
	}
	previous, err := os.ReadFile(h.imageFile + ".previous")
	if err != nil {
		return err
	}
	return os.WriteFile(h.imageFile, previous, 0o644)
}
func (h *fakeHost) WikiVersion(context.Context) (string, error) {
	h.mu.Lock()
	active := h.units[unitWiki] == "active"
	h.mu.Unlock()
	if !active {
		return "", errors.New("connection refused")
	}
	data, _ := os.ReadFile(h.imageFile)
	return h.versions[strings.TrimSpace(string(data))[len("LLM_WIKI_IMAGE="+repository+"@"):]], nil
}
func (h *fakeHost) UIHealthy(context.Context) bool { return h.UnitState(nil, unitUI) == "active" }

func newTestUpdater(t *testing.T, pinned string) (*Updater, *fakeHost) {
	t.Helper()
	dir := t.TempDir()
	cfg := Config{
		Repository: repository, StateDir: filepath.Join(dir, "state"), ImageFile: filepath.Join(dir, "image.env"),
		BackupDir: filepath.Join(dir, "backups"), StopTimeout: time.Second, HealthTimeout: time.Second, AgentTimeout: time.Second,
	}
	if pinned != "" {
		if err := os.WriteFile(cfg.ImageFile, []byte("LLM_WIKI_IMAGE="+repository+"@"+pinned+"\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	host := newFakeHost(cfg.ImageFile)
	u, err := NewUpdater(cfg, host, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	u.poll = time.Millisecond
	u.now = func() time.Time { return time.Date(2026, 10, 13, 12, 0, 0, 0, time.UTC) }
	return u, host
}

func pinnedDigest(t *testing.T, u *Updater) string {
	t.Helper()
	return u.Status().Current.Digest
}

func TestCheckOffersOnlyANewerSignedReleaseOfTheChannel(t *testing.T) {
	u, host := newTestUpdater(t, digest("a"))
	if err := u.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := u.Status().Available; got == nil || got.Tag != "v1.1.0" {
		t.Fatalf("release channel offered %+v", got)
	}

	if err := u.SetChannel(ChannelBeta); err != nil || u.Status().Available != nil {
		t.Fatalf("changing the channel must drop the old offer (err %v)", err)
	}
	if err := u.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := u.Status().Available; got == nil || got.Tag != "v1.2.0-beta.1" {
		t.Fatalf("beta channel offered %+v", got)
	}

	host.badSig["v1.2.0-beta.1"] = true
	if err := u.Check(context.Background()); err == nil {
		t.Fatal("an image without a valid attestation was accepted")
	}
	status := u.Status()
	if status.Available != nil || !strings.Contains(status.CheckError, "release workflow") {
		t.Fatalf("unsigned image offered or failure not reported: %+v", status)
	}
}

func TestCheckLearnsTheRunningTagAndNeverOffersADowngrade(t *testing.T) {
	u, _ := newTestUpdater(t, digest("c"))
	if err := u.SetChannel(ChannelBeta); err != nil {
		t.Fatal(err)
	}
	if err := u.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	if status := u.Status(); status.Available != nil || status.Current.Tag != "v1.2.0-beta.1" {
		t.Fatalf("running beta: %+v", status)
	}
	if err := u.SetChannel(ChannelRelease); err != nil {
		t.Fatal(err)
	}
	if err := u.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := u.Status().Available; got != nil {
		t.Fatalf("leaving beta offered the older release %s", got.Tag)
	}
}

func TestApplyAcceptsOnlyTheOfferedDigest(t *testing.T) {
	u, host := newTestUpdater(t, digest("a"))
	if _, err := u.Apply(digest("b"), "alice"); !errors.Is(err, ErrStale) {
		t.Fatalf("apply before a check: %v", err)
	}
	if err := u.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := u.Apply(digest("c"), "alice"); !errors.Is(err, ErrStale) {
		t.Fatalf("a client named an image the check never offered: %v", err)
	}
	if slices.ContainsFunc(host.Calls(), func(c string) bool { return strings.HasPrefix(c, "pull") }) {
		t.Fatal("a rejected apply touched the machine")
	}
}

func TestUpdateStopsGracefullyArchivesMigratesAndVerifies(t *testing.T) {
	u, host := newTestUpdater(t, digest("a"))
	if err := u.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	host.calls = nil
	if _, err := u.Apply(digest("b"), "alice"); err != nil {
		t.Fatal(err)
	}
	if _, err := u.Apply(digest("b"), "alice"); !errors.Is(err, ErrBusy) {
		t.Fatalf("second apply during an update: %v", err)
	}
	u.Wait()

	want := []string{
		"pull b", "verify v1.1.0", "jobs",
		"systemctl stop llm-wiki-backup.timer",
		"systemctl stop wiki-ui.service wikiagent.service wikisvc.service",
		"archive pre-update-20261013T120000Z-v1.1.0.tar.gz",
		"maintenance wikisvc schema upgrade", "maintenance wikisvc reindex --full", "maintenance wikisvc lint",
		"systemctl start --no-block wikisvc.service wikiagent.service wiki-ui.service",
		"jobs", "systemctl start llm-wiki-backup.timer",
	}
	if got := host.Calls(); !slices.Equal(got, want) {
		t.Fatalf("calls:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	status := u.Status()
	op := status.Operation
	if op.State != "succeeded" || op.StartedBy != "alice" || op.From.Digest != digest("a") || op.To.Tag != "v1.1.0" {
		t.Fatalf("operation: %+v", op)
	}
	if status.Current.Tag != "v1.1.0" || pinnedDigest(t, u) != digest("b") || status.Available != nil {
		t.Fatalf("after update: %+v", status)
	}
	if len(op.JobsBefore) != 1 || len(op.JobsAfter) != 1 {
		t.Fatalf("jobs were not compared: %+v", op)
	}
	previous, _ := os.ReadFile(u.cfg.ImageFile + ".previous")
	if !strings.Contains(string(previous), digest("a")) {
		t.Fatalf("previous pin lost: %q", previous)
	}
	names := []string{}
	for _, step := range op.Steps {
		if step.Status != "done" {
			t.Errorf("step %s ended %s: %s", step.Name, step.Status, step.Detail)
		}
		names = append(names, step.Name)
	}
	if !slices.Equal(names, []string{"pull", "verify", "jobs-before", "stop", "archive", "switch", "migrate", "start", "health", "jobs-after", "timer", "prune"}) {
		t.Fatalf("steps: %v", names)
	}
}

func TestFailureAfterTheSwitchRestoresTheArchive(t *testing.T) {
	for _, failure := range []string{"maintenance wikisvc lint", "version"} {
		t.Run(failure, func(t *testing.T) {
			u, host := newTestUpdater(t, digest("a"))
			if err := u.Check(context.Background()); err != nil {
				t.Fatal(err)
			}
			if failure == "version" {
				host.versions[digest("b")] = "1.0.9" // the image does not run what its tag says
			} else {
				host.fail[failure] = errors.New("lint found errors")
			}
			if _, err := u.Apply(digest("b"), "alice"); err != nil {
				t.Fatal(err)
			}
			u.Wait()

			op := u.Status().Operation
			if op.State != "rolled_back" || op.Error == "" {
				t.Fatalf("operation: %+v", op)
			}
			calls := host.Calls()
			restore := slices.Index(calls, "restore pre-update-20261013T120000Z-v1.1.0.tar.gz")
			if restore < 0 || !slices.Contains(calls[restore:], "maintenance wikisvc reindex --full") {
				t.Fatalf("archive not restored and reindexed:\n%s", strings.Join(calls, "\n"))
			}
			if pinnedDigest(t, u) != digest("a") || u.Status().Current.Digest != digest("a") {
				t.Fatal("the previous image is not running again")
			}
			if host.UnitState(nil, timerBackup) != "active" || host.UnitState(nil, unitAgent) != "active" {
				t.Fatalf("services not back: %v", host.units)
			}
		})
	}
}

func TestFailureBeforeTheSwitchLeavesDataAlone(t *testing.T) {
	for _, failure := range []string{"pull b", "archive pre-update-20261013T120000Z-v1.1.0.tar.gz"} {
		t.Run(failure, func(t *testing.T) {
			u, host := newTestUpdater(t, digest("a"))
			if err := u.Check(context.Background()); err != nil {
				t.Fatal(err)
			}
			host.fail[failure] = errors.New("disk full")
			if _, err := u.Apply(digest("b"), "alice"); err != nil {
				t.Fatal(err)
			}
			u.Wait()

			op := u.Status().Operation
			if op.State != "failed" || slices.ContainsFunc(host.Calls(), func(c string) bool { return strings.HasPrefix(c, "restore") }) {
				t.Fatalf("operation %s restored data it never changed", op.State)
			}
			if pinnedDigest(t, u) != digest("a") {
				t.Fatal("the pin changed")
			}
			for _, unit := range []string{unitWiki, unitAgent, unitUI, timerBackup} {
				if host.UnitState(nil, unit) != "active" {
					t.Fatalf("%s left %s", unit, host.UnitState(nil, unit))
				}
			}
		})
	}
}

func TestHealthWaitsOnlyForWhatRanBefore(t *testing.T) {
	u, host := newTestUpdater(t, digest("a"))
	if err := u.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	host.units[unitAgent] = "activating" // waiting for a model that is down
	host.noStart[unitAgent] = true
	if _, err := u.Apply(digest("b"), "alice"); err != nil {
		t.Fatal(err)
	}
	u.Wait()
	if op := u.Status().Operation; op.State != "succeeded" {
		t.Fatalf("an agent that was already down failed the update: %+v", op)
	}
}

func TestFailedRollbackSaysSo(t *testing.T) {
	u, host := newTestUpdater(t, digest("a"))
	if err := u.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	host.fail["maintenance wikisvc schema upgrade"] = errors.New("migration failed")
	host.fail["restore pre-update-20261013T120000Z-v1.1.0.tar.gz"] = errors.New("archive corrupt")
	if _, err := u.Apply(digest("b"), "alice"); err != nil {
		t.Fatal(err)
	}
	u.Wait()
	op := u.Status().Operation
	if op.State != "failed" || !strings.Contains(op.Error, "migration failed") || !strings.Contains(op.Error, "rollback failed") {
		t.Fatalf("operation: %+v", op)
	}
}

func TestAnUpdateCutShortIsReportedNotGuessed(t *testing.T) {
	u, _ := newTestUpdater(t, digest("a"))
	u.state.Operation = &Operation{ID: "x", State: "running", Archive: "/var/backups/llm-wiki/pre-update-x.tar.gz"}
	if err := u.saveLocked(); err != nil {
		t.Fatal(err)
	}
	again, err := NewUpdater(u.cfg, u.host, u.log)
	if err != nil {
		t.Fatal(err)
	}
	op := again.Status().Operation
	if op.State != "interrupted" || !strings.Contains(op.Error, "pre-update-x.tar.gz") {
		t.Fatalf("operation: %+v", op)
	}
}

func TestASuccessfulUpdateKeepsTheThreeNewestArchives(t *testing.T) {
	u, _ := newTestUpdater(t, digest("a"))
	if err := os.MkdirAll(u.cfg.BackupDir, 0o700); err != nil {
		t.Fatal(err)
	}
	names := []string{
		"pre-update-20261001T000000Z-v0.9.0.tar.gz", "pre-update-20261005T000000Z-v0.9.1.tar.gz",
		"pre-update-20261009T000000Z-v0.9.2.tar.gz", "pre-update-20261011T000000Z-v1.0.0.tar.gz",
		"pre-update-20261013T120000Z-v1.1.0.tar.gz", "data-20261001T000000Z-x.tar.gz",
	}
	for _, name := range names {
		if err := os.WriteFile(filepath.Join(u.cfg.BackupDir, name), nil, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	if err := u.Check(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := u.Apply(digest("b"), "alice"); err != nil {
		t.Fatal(err)
	}
	u.Wait()
	entries, _ := os.ReadDir(u.cfg.BackupDir)
	left := []string{}
	for _, entry := range entries {
		left = append(left, entry.Name())
	}
	want := []string{names[5], names[2], names[3], names[4]}
	if !slices.Equal(left, want) {
		t.Fatalf("archives left %v, want %v", left, want)
	}
}
