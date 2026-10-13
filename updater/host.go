package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// Image is what the registry says about one release tag.
type Image struct {
	Tag      string `json:"tag"`
	Digest   string `json:"digest"`
	Revision string `json:"revision"`
}

// Job is one line of `wikiagent jobs`: the agent resumes it after a restart.
type Job struct {
	ID        string `json:"id"`
	Kind      string `json:"kind"`
	Status    string `json:"status"`
	UpdatedAt string `json:"updated_at"`
}

// Host is everything an update does to the machine. The update itself is written
// against this interface, so its order and its rollback are tested without root.
type Host interface {
	Tags(ctx context.Context) ([]string, error)
	Inspect(ctx context.Context, tag string) (Image, error)
	Verify(ctx context.Context, tag, digest string) error
	Pull(ctx context.Context, digest string) error
	Jobs(ctx context.Context) ([]Job, error)
	Systemctl(ctx context.Context, args ...string) error
	UnitState(ctx context.Context, unit string) string
	Maintenance(ctx context.Context, args ...string) error
	Archive(ctx context.Context, path string) error
	Restore(ctx context.Context, path, suffix string) error
	WikiVersion(ctx context.Context) (string, error)
	UIHealthy(ctx context.Context) bool
}

// Runner starts one program and returns its standard output.
type Runner interface {
	Run(ctx context.Context, name string, args ...string) ([]byte, error)
}

type execRunner struct{}

func (execRunner) Run(ctx context.Context, name string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		// Commands never carry secrets. The cause is often a line before the last
		// one (tar names the failing file, then says it gives up), so keep a few.
		lines := strings.Split(strings.TrimSpace(stderr.String()), "\n")
		lines = lines[max(0, len(lines)-4):]
		return out, fmt.Errorf("%s %s: %w: %s", filepath.Base(name), strings.Join(args, " "), err, strings.Join(lines, " | "))
	}
	return out, nil
}

// Data the services write and the configuration they read. A pre-update archive
// holds exactly these, like the nightly backup; the index is rebuilt instead.
var archived = []string{"var/lib/llm-wiki/wiki", "var/lib/llm-wiki/state", "var/lib/llm-wiki/agent", "etc/llm-wiki"}

var digestPattern = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)

// System is the real Host: the distribution's podman, systemctl and tar, skopeo and
// cosign from the host bundle, and llm-wiki-run for every container.
type System struct {
	cfg  Config
	run  Runner
	http *http.Client
}

func (s *System) Tags(ctx context.Context) ([]string, error) {
	out, err := s.run.Run(ctx, s.cfg.Skopeo, "list-tags", "docker://"+s.cfg.Repository)
	if err != nil {
		return nil, err
	}
	var listing struct{ Tags []string }
	if err := json.Unmarshal(out, &listing); err != nil {
		return nil, fmt.Errorf("skopeo list-tags: %w", err)
	}
	return listing.Tags, nil
}

func (s *System) Inspect(ctx context.Context, tag string) (Image, error) {
	out, err := s.run.Run(ctx, s.cfg.Skopeo, "inspect", "docker://"+s.cfg.Repository+":"+tag)
	if err != nil {
		return Image{}, err
	}
	var manifest struct {
		Digest string
		Labels map[string]string
	}
	if err := json.Unmarshal(out, &manifest); err != nil {
		return Image{}, fmt.Errorf("skopeo inspect: %w", err)
	}
	if !digestPattern.MatchString(manifest.Digest) {
		return Image{}, fmt.Errorf("registry returned no sha256 digest for %s", tag)
	}
	return Image{Tag: tag, Digest: manifest.Digest, Revision: manifest.Labels["org.opencontainers.image.revision"]}, nil
}

// Verify accepts the digest only if this repository's release workflow attested
// building it for exactly this tag: a signature for another tag or workflow fails.
func (s *System) Verify(ctx context.Context, tag, digest string) error {
	_, err := s.run.Run(ctx, s.cfg.Cosign, "verify-attestation",
		"--type", "https://slsa.dev/provenance/v1",
		"--certificate-oidc-issuer", s.cfg.Issuer,
		"--certificate-identity", s.cfg.Identity+tag,
		s.cfg.Repository+"@"+digest)
	return err
}

func (s *System) Pull(ctx context.Context, digest string) error {
	_, err := s.run.Run(ctx, s.cfg.Podman, "pull", "--quiet", s.cfg.Repository+"@"+digest)
	return err
}

func (s *System) Jobs(ctx context.Context) ([]Job, error) {
	out, err := s.run.Run(ctx, s.cfg.RunScript, "once", "maintenance", "wikiagent", "jobs")
	if err != nil {
		return nil, err
	}
	var jobs []Job
	if err := json.Unmarshal(out, &jobs); err != nil {
		return nil, fmt.Errorf("wikiagent jobs: %w", err)
	}
	return jobs, nil
}

func (s *System) Systemctl(ctx context.Context, args ...string) error {
	_, err := s.run.Run(ctx, s.cfg.Systemctl, args...)
	return err
}

// UnitState is active, activating, inactive, failed…; a running oneshot such as the
// backup job is "activating". is-active exits non-zero for every state but active,
// so its output, not its exit code, is the answer.
func (s *System) UnitState(ctx context.Context, unit string) string {
	out, _ := s.run.Run(ctx, s.cfg.Systemctl, "is-active", unit)
	return strings.TrimSpace(string(out))
}

func (s *System) Maintenance(ctx context.Context, args ...string) error {
	_, err := s.run.Run(ctx, s.cfg.RunScript, append([]string{"once", "maintenance"}, args...)...)
	return err
}

func (s *System) Archive(ctx context.Context, path string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	if _, err := s.run.Run(ctx, s.cfg.Tar, append([]string{"-C", s.cfg.Root, "-czf", path}, archived...)...); err != nil {
		_ = os.Remove(path) // an incomplete archive must never pass for a backup
		return err
	}
	return os.Chmod(path, 0o600)
}

// Restore moves the current data aside, keeping it for inspection, and unpacks the
// archive in its place; tar running as root restores owners and modes.
func (s *System) Restore(ctx context.Context, path, suffix string) error {
	for _, relative := range archived {
		current := filepath.Join(s.cfg.Root, relative)
		if _, err := os.Lstat(current); errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err := os.Rename(current, current+".failed-"+suffix); err != nil {
			return err
		}
	}
	_, err := s.run.Run(ctx, s.cfg.Tar, "-C", s.cfg.Root, "-xzf", path)
	return err
}

func (s *System) WikiVersion(ctx context.Context) (string, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, s.cfg.WikiURL+"/api/v1/health", nil)
	if err != nil {
		return "", err
	}
	response, err := s.http.Do(request)
	if err != nil {
		return "", err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return "", fmt.Errorf("wikisvc health: HTTP %d", response.StatusCode)
	}
	var health struct{ Version string }
	if err := json.NewDecoder(response.Body).Decode(&health); err != nil {
		return "", fmt.Errorf("wikisvc health: %w", err)
	}
	return health.Version, nil
}

func (s *System) UIHealthy(ctx context.Context) bool {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, s.cfg.UIURL+"/healthz", nil)
	if err != nil {
		return false
	}
	response, err := s.http.Do(request)
	if err != nil {
		return false
	}
	response.Body.Close()
	return response.StatusCode == http.StatusOK
}
