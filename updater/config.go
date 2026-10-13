package main

import (
	"flag"
	"time"
)

// Config is fixed when the daemon starts; the defaults describe the standard install.
type Config struct {
	Repository string // release images
	Identity   string // signer identity prefix; the tag completes it
	Issuer     string // OIDC issuer of that identity
	StateDir   string // the updater's own state, outside the data it restores
	ImageFile  string // the image the services run, pinned by digest
	BackupDir  string
	WikiURL    string
	UIURL      string
	CheckEvery time.Duration
	Root       string // filesystem the archive is taken from and restored to: always / in service

	Skopeo, Cosign, Podman, Systemctl, Tar, RunScript string

	StopTimeout   time.Duration // wikiagent alone may take 11 minutes to pause its jobs
	HealthTimeout time.Duration // wikisvc and wiki-ui answering after a start
	AgentTimeout  time.Duration // wikiagent waits up to 10 minutes for the model
}

func parseConfig(args []string) (Config, error) {
	c := Config{Root: "/"}
	f := flag.NewFlagSet("llm-wiki-updater", flag.ContinueOnError)
	f.StringVar(&c.Repository, "repository", "ghcr.io/badrabbit00/llm-wiki", "release image repository")
	f.StringVar(&c.Identity, "identity", "https://github.com/BadRabbit00/llm-wiki/.github/workflows/release.yml@refs/tags/", "signer identity prefix")
	f.StringVar(&c.Issuer, "issuer", "https://token.actions.githubusercontent.com", "signer OIDC issuer")
	f.StringVar(&c.StateDir, "state-dir", "/var/lib/llm-wiki-updater", "updater state")
	f.StringVar(&c.ImageFile, "image-file", "/etc/llm-wiki/image.env", "pinned service image")
	f.StringVar(&c.BackupDir, "backup-dir", "/var/backups/llm-wiki", "pre-update archives")
	f.StringVar(&c.WikiURL, "wiki-url", "http://127.0.0.1:8787", "wikisvc origin")
	f.StringVar(&c.UIURL, "ui-url", "http://127.0.0.1:8789", "wiki-ui origin")
	f.DurationVar(&c.CheckEvery, "check-every", 6*time.Hour, "registry check interval")
	f.StringVar(&c.Skopeo, "skopeo", "skopeo", "skopeo binary")
	f.StringVar(&c.Cosign, "cosign", "cosign", "cosign binary")
	f.StringVar(&c.Podman, "podman", "/usr/bin/podman", "podman binary")
	f.StringVar(&c.Systemctl, "systemctl", "/usr/bin/systemctl", "systemctl binary")
	f.StringVar(&c.Tar, "tar", "/usr/bin/tar", "GNU tar binary")
	f.StringVar(&c.RunScript, "run", "/opt/llm-wiki/current/bin/llm-wiki-run", "llm-wiki-run")
	f.DurationVar(&c.StopTimeout, "stop-timeout", 15*time.Minute, "service stop limit")
	f.DurationVar(&c.HealthTimeout, "health-timeout", 3*time.Minute, "wikisvc and wiki-ui start limit")
	f.DurationVar(&c.AgentTimeout, "agent-timeout", 12*time.Minute, "wikiagent start limit")
	err := f.Parse(args)
	return c, err
}
