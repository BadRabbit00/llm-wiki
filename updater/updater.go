package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

var (
	ErrBusy    = errors.New("an update or a check is already running")
	ErrStale   = errors.New("the offered update is no longer current; check again")
	ErrChannel = errors.New("unknown channel")
)

const (
	unitWiki    = "wikisvc.service"
	unitAgent   = "wikiagent.service"
	unitUI      = "wiki-ui.service"
	unitBackup  = "llm-wiki-backup.service"
	timerBackup = "llm-wiki-backup.timer"
)

// Stopped together: systemd orders the stop by the units' own dependencies.
var services = []string{unitUI, unitAgent, unitWiki}

type Step struct {
	Name   string    `json:"name"`
	Status string    `json:"status"` // running, done, failed
	At     time.Time `json:"at"`
	Detail string    `json:"detail,omitempty"`
}

type Operation struct {
	ID         string     `json:"id"`
	From       Image      `json:"from"`
	To         Image      `json:"to"`
	StartedBy  string     `json:"started_by"`
	State      string     `json:"state"` // running, succeeded, rolled_back, failed, interrupted
	Steps      []Step     `json:"steps"`
	JobsBefore []Job      `json:"jobs_before"`
	JobsAfter  []Job      `json:"jobs_after"`
	Archive    string     `json:"archive,omitempty"`
	Error      string     `json:"error,omitempty"`
	StartedAt  time.Time  `json:"started_at"`
	FinishedAt *time.Time `json:"finished_at,omitempty"`
}

type State struct {
	Channel    string     `json:"channel"`
	Current    Image      `json:"current"`
	Available  *Image     `json:"available"`
	CheckedAt  *time.Time `json:"checked_at"`
	CheckError string     `json:"check_error,omitempty"`
	Operation  *Operation `json:"operation"`
}

type Updater struct {
	cfg  Config
	host Host
	now  func() time.Time
	poll time.Duration
	log  *slog.Logger

	mu       sync.Mutex
	state    State
	checking bool
	applying bool
	done     chan struct{} // closed when the running operation finishes
}

func NewUpdater(cfg Config, host Host, log *slog.Logger) (*Updater, error) {
	u := &Updater{cfg: cfg, host: host, now: time.Now, poll: 2 * time.Second, log: log, state: State{Channel: ChannelRelease}}
	data, err := os.ReadFile(u.statePath())
	switch {
	case errors.Is(err, os.ErrNotExist):
	case err != nil:
		return nil, err
	default:
		if err := json.Unmarshal(data, &u.state); err != nil {
			return nil, fmt.Errorf("%s: %w", u.statePath(), err)
		}
	}
	if op := u.state.Operation; op != nil && op.State == "running" {
		// The daemon stopped mid-update. Guessing which half of the update the machine
		// is in would be worse than saying so: a person checks the services and data.
		op.State = "interrupted"
		op.Error = "the updater stopped during the update; check the services and, if needed, restore " + op.Archive
		now := u.now()
		op.FinishedAt = &now
	}
	return u, u.saveLocked()
}

func (u *Updater) statePath() string { return filepath.Join(u.cfg.StateDir, "state.json") }

func (u *Updater) saveLocked() error {
	data, err := json.MarshalIndent(u.state, "", "  ")
	if err != nil {
		return err
	}
	return writeAtomically(u.statePath(), data, 0o600)
}

func writeAtomically(path string, data []byte, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+".*")
	if err != nil {
		return err
	}
	defer os.Remove(temporary.Name())
	if _, err := temporary.Write(data); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Chmod(temporary.Name(), mode); err != nil {
		return err
	}
	return os.Rename(temporary.Name(), path)
}

var pinPattern = regexp.MustCompile(`^LLM_WIKI_IMAGE=(.+)@(sha256:[0-9a-f]{64})$`)

// pinned reads the digest the services run; image.env, not the updater, is the truth.
func (u *Updater) pinned() string {
	data, err := os.ReadFile(u.cfg.ImageFile)
	if err != nil {
		return ""
	}
	digest := ""
	for _, line := range strings.Split(string(data), "\n") {
		if match := pinPattern.FindStringSubmatch(strings.TrimSpace(line)); match != nil && match[1] == u.cfg.Repository {
			digest = match[2]
		}
	}
	return digest
}

// currentLocked names the running image; its tag is known once a check or an update saw it.
func (u *Updater) currentLocked() Image {
	digest := u.pinned()
	if u.state.Current.Digest == digest {
		return u.state.Current
	}
	return Image{Digest: digest}
}

func (u *Updater) Status() State {
	u.mu.Lock()
	defer u.mu.Unlock()
	status := u.state
	status.Current = u.currentLocked()
	if status.Operation != nil {
		op := *status.Operation
		op.Steps = append([]Step(nil), op.Steps...)
		status.Operation = &op
	}
	return status
}

func (u *Updater) SetChannel(channel string) error {
	if channel != ChannelRelease && channel != ChannelBeta {
		return ErrChannel
	}
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.applying {
		return ErrBusy
	}
	if u.state.Channel != channel {
		u.state.Channel, u.state.Available = channel, nil
	}
	return u.saveLocked()
}

// Check asks the registry for the newest tag of the channel and offers it only when
// it is newer than what runs and its signature proves where it was built.
func (u *Updater) Check(ctx context.Context) error {
	u.mu.Lock()
	if u.applying || u.checking {
		u.mu.Unlock()
		return ErrBusy
	}
	u.checking = true
	channel, current := u.state.Channel, u.currentLocked()
	u.mu.Unlock()

	available, runningTag, err := u.discover(ctx, channel, current)

	u.mu.Lock()
	defer u.mu.Unlock()
	u.checking = false
	now := u.now()
	u.state.CheckedAt = &now
	if err != nil {
		// A tag that now points at something unverifiable is no time to keep offering
		// what it pointed at before; an unreachable registry just means "try later".
		u.state.CheckError, u.state.Available = err.Error(), nil
		u.log.Warn("update check failed", "error", err)
	} else {
		u.state.CheckError, u.state.Available = "", available
		if runningTag != "" {
			u.state.Current = Image{Tag: runningTag, Digest: current.Digest, Revision: u.state.Current.Revision}
		}
	}
	if saveErr := u.saveLocked(); saveErr != nil {
		return saveErr
	}
	return err
}

func (u *Updater) discover(ctx context.Context, channel string, current Image) (*Image, string, error) {
	tags, err := u.host.Tags(ctx)
	if err != nil {
		return nil, "", err
	}
	latest, ok := Latest(tags, channel)
	if !ok {
		return nil, "", nil
	}
	image, err := u.host.Inspect(ctx, latest.Tag)
	if err != nil {
		return nil, "", err
	}
	if image.Digest == current.Digest {
		return nil, latest.Tag, nil
	}
	if running, ok := ParseVersion(current.Tag); ok && !running.Less(latest) {
		return nil, "", nil // switching channel never offers a downgrade
	}
	if err := u.host.Verify(ctx, latest.Tag, image.Digest); err != nil {
		return nil, "", fmt.Errorf("signature of %s does not prove it was built by the release workflow: %w", latest.Tag, err)
	}
	return &image, "", nil
}

// Apply starts installing the offered update. The digest must be the one the check
// offered, so a client can only confirm an update, never name an image.
func (u *Updater) Apply(digest, by string) (*Operation, error) {
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.applying || u.checking {
		return nil, ErrBusy
	}
	if u.state.Available == nil || u.state.Available.Digest != digest {
		return nil, ErrStale
	}
	now := u.now()
	op := &Operation{
		ID:        now.UTC().Format("20060102T150405Z"),
		From:      u.currentLocked(),
		To:        *u.state.Available,
		StartedBy: by,
		State:     "running",
		StartedAt: now,
	}
	u.state.Operation, u.applying, u.done = op, true, make(chan struct{})
	if err := u.saveLocked(); err != nil {
		u.applying = false
		return nil, err
	}
	u.log.Info("update started", "from", op.From.Tag, "to", op.To.Tag, "digest", op.To.Digest, "by", by)
	go u.run(op)
	return op, nil
}

// Wait blocks until the running update, if any, has finished.
func (u *Updater) Wait() {
	u.mu.Lock()
	done := u.done
	u.mu.Unlock()
	if done != nil {
		<-done
	}
}

func (u *Updater) record(op *Operation, step Step) {
	u.mu.Lock()
	defer u.mu.Unlock()
	if n := len(op.Steps); n > 0 && op.Steps[n-1].Name == step.Name {
		op.Steps[n-1] = step
	} else {
		op.Steps = append(op.Steps, step)
	}
	if err := u.saveLocked(); err != nil {
		u.log.Error("cannot save update state", "error", err)
	}
}

func (u *Updater) step(op *Operation, name string, action func() (string, error)) error {
	u.record(op, Step{Name: name, Status: "running", At: u.now()})
	detail, err := action()
	status := "done"
	if err != nil {
		status, detail = "failed", err.Error()
		u.log.Warn("update step failed", "step", name, "error", err)
	}
	u.record(op, Step{Name: name, Status: status, At: u.now(), Detail: detail})
	return err
}

func (u *Updater) finish(op *Operation, state string, cause error) {
	u.mu.Lock()
	defer u.mu.Unlock()
	now := u.now()
	op.State, op.FinishedAt = state, &now
	if cause != nil {
		op.Error = cause.Error()
	}
	if state == "succeeded" {
		u.state.Current, u.state.Available = op.To, nil
	}
	if err := u.saveLocked(); err != nil {
		u.log.Error("cannot save update state", "error", err)
	}
	u.applying = false
	close(u.done)
	u.log.Info("update finished", "state", state, "to", op.To.Tag, "error", op.Error)
}

func (u *Updater) waitFor(ctx context.Context, timeout time.Duration, what string, ready func(context.Context) bool) error {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	for {
		if ready(ctx) {
			return nil
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("%s: not ready after %s", what, timeout)
		case <-time.After(u.poll):
		}
	}
}

func (u *Updater) run(op *Operation) {
	ctx := context.Background()
	target, _ := ParseVersion(op.To.Tag)

	// Until the services stop, nothing has changed and a failure needs no undo.
	if err := u.step(op, "pull", func() (string, error) { return "", u.host.Pull(ctx, op.To.Digest) }); err != nil {
		u.finish(op, "failed", err)
		return
	}
	if err := u.step(op, "verify", func() (string, error) { return "", u.host.Verify(ctx, op.To.Tag, op.To.Digest) }); err != nil {
		u.finish(op, "failed", err)
		return
	}
	_ = u.step(op, "jobs-before", func() (string, error) {
		jobs, err := u.host.Jobs(ctx)
		if err != nil {
			return "not available: " + err.Error(), nil // the old image may predate `wikiagent jobs`
		}
		u.mu.Lock()
		op.JobsBefore = jobs
		u.mu.Unlock()
		return fmt.Sprintf("%d resumable", len(jobs)), nil
	})
	before := map[string]bool{}
	for _, unit := range append([]string{timerBackup}, services...) {
		before[unit] = u.host.UnitState(ctx, unit) == "active"
	}

	if err := u.step(op, "stop", func() (string, error) { return "", u.stop(ctx) }); err != nil {
		u.resume(op, before)
		u.finish(op, "failed", err)
		return
	}
	archive := filepath.Join(u.cfg.BackupDir, "pre-update-"+op.ID+"-"+op.To.Tag+".tar.gz")
	if err := u.step(op, "archive", func() (string, error) { return archive, u.host.Archive(ctx, archive) }); err != nil {
		u.resume(op, before)
		u.finish(op, "failed", err)
		return
	}
	u.mu.Lock()
	op.Archive = archive
	u.mu.Unlock()

	// From here on the data may change; any failure restores the archive.
	err := u.step(op, "switch", func() (string, error) { return op.To.Tag, u.pin(op.To.Digest) })
	if err == nil {
		err = u.step(op, "migrate", func() (string, error) { return "", u.migrate(ctx) })
	}
	if err == nil {
		err = u.step(op, "start", func() (string, error) { return "", u.start(ctx) })
	}
	if err == nil {
		err = u.step(op, "health", func() (string, error) { return u.healthy(ctx, before, target.Base()) })
	}
	if err != nil {
		u.rollback(op, before, err)
		return
	}
	_ = u.step(op, "jobs-after", func() (string, error) {
		jobs, err := u.host.Jobs(ctx)
		if err != nil {
			return "not available: " + err.Error(), nil
		}
		u.mu.Lock()
		op.JobsAfter = jobs
		u.mu.Unlock()
		return fmt.Sprintf("%d resumable", len(jobs)), nil
	})
	if before[timerBackup] {
		_ = u.step(op, "timer", func() (string, error) { return "", u.host.Systemctl(ctx, "start", timerBackup) })
	}
	_ = u.step(op, "prune", u.prune)
	u.finish(op, "succeeded", nil)
}

// stop waits out a running backup job, then stops the services. The agent finishes
// open chat replies and pauses its jobs at their next checkpoint before it exits.
func (u *Updater) stop(ctx context.Context) error {
	if err := u.host.Systemctl(ctx, "stop", timerBackup); err != nil {
		return err
	}
	if err := u.waitFor(ctx, u.cfg.StopTimeout, "backup job", func(ctx context.Context) bool {
		state := u.host.UnitState(ctx, unitBackup)
		return state != "active" && state != "activating" && state != "deactivating"
	}); err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, u.cfg.StopTimeout)
	defer cancel()
	return u.host.Systemctl(ctx, append([]string{"stop"}, services...)...)
}

func (u *Updater) migrate(ctx context.Context) error {
	for _, command := range [][]string{{"wikisvc", "schema", "upgrade"}, {"wikisvc", "reindex", "--full"}, {"wikisvc", "lint"}} {
		if err := u.host.Maintenance(ctx, command...); err != nil {
			return err
		}
	}
	return nil
}

// start does not block on the agent, whose start waits for the model; health does.
func (u *Updater) start(ctx context.Context) error {
	return u.host.Systemctl(ctx, append([]string{"start", "--no-block"}, unitWiki, unitAgent, unitUI)...)
}

// healthy requires every service that ran before the update to run after it, and
// wikisvc to report the expected version (any version when version is empty).
func (u *Updater) healthy(ctx context.Context, before map[string]bool, version string) (string, error) {
	reported := ""
	if err := u.waitFor(ctx, u.cfg.HealthTimeout, "wikisvc", func(ctx context.Context) bool {
		reported, _ = u.host.WikiVersion(ctx)
		return reported != "" && (version == "" || reported == version)
	}); err != nil {
		if reported != "" {
			return "", fmt.Errorf("wikisvc reports version %s, expected %s", reported, version)
		}
		return "", err
	}
	if before[unitUI] {
		if err := u.waitFor(ctx, u.cfg.HealthTimeout, "wiki-ui", u.host.UIHealthy); err != nil {
			return "", err
		}
	}
	if before[unitAgent] {
		if err := u.waitFor(ctx, u.cfg.AgentTimeout, "wikiagent", func(ctx context.Context) bool {
			return u.host.UnitState(ctx, unitAgent) == "active"
		}); err != nil {
			return "", err
		}
	}
	return "wikisvc " + reported, nil
}

// pin points the services at the new digest, keeping the old line for a manual rollback.
func (u *Updater) pin(digest string) error {
	if previous, err := os.ReadFile(u.cfg.ImageFile); err == nil {
		if err := writeAtomically(u.cfg.ImageFile+".previous", previous, 0o644); err != nil {
			return err
		}
	}
	return writeAtomically(u.cfg.ImageFile, []byte("LLM_WIKI_IMAGE="+u.cfg.Repository+"@"+digest+"\n"), 0o644)
}

// resume brings back what the update stopped when it failed before changing data.
func (u *Updater) resume(op *Operation, before map[string]bool) {
	_ = u.step(op, "resume", func() (string, error) {
		ctx := context.Background()
		if err := u.start(ctx); err != nil {
			return "", err
		}
		if before[timerBackup] {
			return "", u.host.Systemctl(ctx, "start", timerBackup)
		}
		return "", nil
	})
}

// rollback restores the pre-update archive, which also restores image.env and with
// it the previous image, rebuilds the index with that image and starts the services.
func (u *Updater) rollback(op *Operation, before map[string]bool, cause error) {
	ctx := context.Background()
	previous := ""
	if v, ok := ParseVersion(op.From.Tag); ok {
		previous = v.Base()
	}
	err := u.step(op, "rollback", func() (string, error) {
		stopCtx, cancel := context.WithTimeout(ctx, u.cfg.StopTimeout)
		defer cancel()
		_ = u.host.Systemctl(stopCtx, append([]string{"stop"}, services...)...) // some may never have started
		if err := u.host.Restore(ctx, op.Archive, op.ID); err != nil {
			return "", fmt.Errorf("restore %s: %w", op.Archive, err)
		}
		if err := u.host.Maintenance(ctx, "wikisvc", "reindex", "--full"); err != nil {
			return "", fmt.Errorf("reindex: %w", err)
		}
		if err := u.start(ctx); err != nil {
			return "", err
		}
		detail, err := u.healthy(ctx, before, previous)
		if err != nil {
			return "", err
		}
		if before[timerBackup] {
			return detail, u.host.Systemctl(ctx, "start", timerBackup)
		}
		return detail, nil
	})
	if err != nil {
		u.finish(op, "failed", fmt.Errorf("%w; rollback failed: %v", cause, err))
		return
	}
	u.finish(op, "rolled_back", cause)
}

// keepArchives pre-update archives survive a successful update. The nightly backup's
// retention covers only data-*.tar.gz, so without this every update would leave a
// full copy of the data behind for good.
const keepArchives = 3

func (u *Updater) prune() (string, error) {
	entries, err := os.ReadDir(u.cfg.BackupDir)
	if errors.Is(err, os.ErrNotExist) {
		return "nothing to prune", nil
	}
	if err != nil {
		return "", err
	}
	var archives []string
	for _, entry := range entries {
		name := entry.Name()
		if entry.Type().IsRegular() && strings.HasPrefix(name, "pre-update-") && strings.HasSuffix(name, ".tar.gz") {
			archives = append(archives, name)
		}
	}
	sort.Strings(archives) // names begin with the UTC start time: oldest first
	removed := 0
	for len(archives) > keepArchives {
		if err := os.Remove(filepath.Join(u.cfg.BackupDir, archives[0])); err != nil {
			return "", err
		}
		archives, removed = archives[1:], removed+1
	}
	return fmt.Sprintf("%d removed, %d kept", removed, len(archives)), nil
}
