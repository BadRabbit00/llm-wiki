// doc: MOD-updater.main

// llm-wiki-updater checks for signed release images and installs one when a human
// administrator confirms it in the interface: it stops the services gracefully,
// archives their data, switches the pinned digest, migrates, verifies the result
// and restores the archive when anything after the switch fails.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"
)

// doc: CLI-updater.serve
func main() {
	if len(os.Args) < 2 || os.Args[1] != "serve" {
		fmt.Fprintln(os.Stderr, "Usage: llm-wiki-updater serve [flags]")
		os.Exit(2)
	}
	cfg, err := parseConfig(os.Args[2:])
	if err != nil {
		os.Exit(2)
	}
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	if err := serve(cfg, log); err != nil {
		log.Error("llm-wiki-updater stopped", "error", err)
		os.Exit(1)
	}
}

func serve(cfg Config, log *slog.Logger) error {
	listener, err := systemdListener()
	if err != nil {
		return err
	}
	client := &http.Client{Timeout: 10 * time.Second}
	updater, err := NewUpdater(cfg, &System{cfg: cfg, run: execRunner{}, http: client}, log)
	if err != nil {
		return err
	}
	api := &API{updater: updater, whoami: wikiWhoAmI(cfg.WikiURL, client)}
	server := &http.Server{
		Handler:           api.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      3 * time.Minute,
		IdleTimeout:       time.Minute,
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	go checkPeriodically(ctx, updater, cfg.CheckEvery, log)
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Info("llm-wiki-updater listening", "repository", cfg.Repository)
	if err := server.Serve(listener); !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	// Leaving mid-update would strand stopped services; the unit's stop timeout covers it.
	updater.Wait()
	return nil
}

// doc: JOB-updater.check
func checkPeriodically(ctx context.Context, updater *Updater, every time.Duration, log *slog.Logger) {
	timer := time.NewTimer(time.Minute)
	defer timer.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-timer.C:
		}
		check, cancel := context.WithTimeout(ctx, 2*time.Minute)
		if err := updater.Check(check); err != nil && !errors.Is(err, ErrBusy) {
			log.Warn("scheduled update check failed", "error", err)
		}
		cancel()
		timer.Reset(every)
	}
}

// systemdListener takes the socket llm-wiki-updater.socket created with the group
// and mode that let only wiki-ui connect; the daemon never opens a port itself.
func systemdListener() (net.Listener, error) {
	// doc: CFG-updater.LISTEN_PID, CFG-updater.LISTEN_FDS
	if os.Getenv("LISTEN_PID") != strconv.Itoa(os.Getpid()) || os.Getenv("LISTEN_FDS") != "1" {
		return nil, errors.New("start llm-wiki-updater through llm-wiki-updater.socket")
	}
	// The commands the updater runs must not believe they were socket-activated.
	for _, name := range []string{"LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES"} {
		_ = os.Unsetenv(name)
	}
	file := os.NewFile(3, "llm-wiki-updater.socket")
	defer file.Close()
	return net.FileListener(file)
}
