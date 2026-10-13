package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// whoamiFor answers like wikisvc for a few tokens.
func whoamiFor(t *testing.T) WhoAmI {
	t.Helper()
	principals := map[string]Principal{
		"Bearer admin":  {Kind: "human", Role: "admin", Name: "alice", Identity: "opaque-alice"},
		"Bearer agent":  {Kind: "agent", Role: "admin", Name: "wikiagent"},
		"Bearer reader": {Kind: "human", Role: "reviewer", Name: "bob"},
	}
	return func(_ context.Context, authorization string) (Principal, int, error) {
		if authorization == "Bearer down" {
			return Principal{}, 0, errors.New("connection refused")
		}
		principal, ok := principals[authorization]
		if !ok {
			return Principal{}, http.StatusUnauthorized, nil
		}
		return principal, http.StatusOK, nil
	}
}

func request(t *testing.T, handler http.Handler, method, path, token, body string) (int, map[string]any) {
	t.Helper()
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)
	var decoded map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &decoded); err != nil {
		t.Fatalf("%s %s: %v: %s", method, path, err, w.Body)
	}
	return w.Code, decoded
}

func errorCode(body map[string]any) string {
	if e, ok := body["error"].(map[string]any); ok {
		code, _ := e["code"].(string)
		return code
	}
	return ""
}

func TestOnlyAHumanAdministratorReachesTheUpdater(t *testing.T) {
	u, _ := newTestUpdater(t, digest("a"))
	handler := (&API{updater: u, whoami: whoamiFor(t)}).Handler()
	for token, want := range map[string]string{
		"":       "E_UNAUTHORIZED",
		"forged": "E_UNAUTHORIZED",
		"down":   "E_SERVICE_UNAVAILABLE",
		"agent":  "E_HUMAN_REQUIRED",
		"reader": "E_FORBIDDEN",
	} {
		for _, call := range [][2]string{{"GET", "/v1/status"}, {"POST", "/v1/check"}, {"PUT", "/v1/channel"}, {"POST", "/v1/apply"}} {
			if _, body := request(t, handler, call[0], call[1], token, `{}`); errorCode(body) != want {
				t.Errorf("%s %s as %q: %v, want %s", call[0], call[1], token, body, want)
			}
		}
	}
	if status, body := request(t, handler, "GET", "/v1/status", "admin", ""); status != http.StatusOK || body["channel"] != ChannelRelease {
		t.Fatalf("admin status %d %v", status, body)
	}
}

func TestCheckChannelAndApplyThroughTheAPI(t *testing.T) {
	u, _ := newTestUpdater(t, digest("a"))
	handler := (&API{updater: u, whoami: whoamiFor(t)}).Handler()

	status, body := request(t, handler, "POST", "/v1/check", "admin", "")
	available, _ := body["available"].(map[string]any)
	if status != http.StatusOK || available["tag"] != "v1.1.0" {
		t.Fatalf("check %d %v", status, body)
	}
	for payload, want := range map[string]string{
		`{"channel":"nightly"}`:            "E_UPDATE_CHANNEL",
		`{"channel":"beta","extra":true}`:  "E_BAD_REQUEST",
		`{"digest":"` + digest("c") + `"}`: "E_BAD_REQUEST", // not a channel field
	} {
		if _, body := request(t, handler, "PUT", "/v1/channel", "admin", payload); errorCode(body) != want {
			t.Errorf("channel %s: %v, want %s", payload, body, want)
		}
	}
	if _, body := request(t, handler, "POST", "/v1/apply", "admin", `{"digest":"`+digest("c")+`"}`); errorCode(body) != "E_UPDATE_STALE" {
		t.Fatalf("apply of an image never offered: %v", body)
	}
	status, body = request(t, handler, "POST", "/v1/apply", "admin", `{"digest":"`+digest("b")+`"}`)
	operation, _ := body["operation"].(map[string]any)
	if status != http.StatusAccepted || operation["started_by"] != "opaque-alice" {
		t.Fatalf("apply %d %v", status, body)
	}
	u.Wait()
	if op := u.Status().Operation; op.State != "succeeded" {
		t.Fatalf("operation %+v", op)
	}
	status, body = request(t, handler, "PUT", "/v1/channel", "admin", `{"channel":"beta"}`)
	available, _ = body["available"].(map[string]any)
	if status != http.StatusOK || body["channel"] != ChannelBeta || available["tag"] != "v1.2.0-beta.1" {
		t.Fatalf("switching to beta %d %v", status, body)
	}
}

func TestWhoAmIAsksWikisvcWithTheCallersToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/whoami" || r.Header.Get("Authorization") != "Bearer admin" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		_, _ = w.Write([]byte(`{"kind":"human","role":"admin","name":"alice","identity":"opaque-alice","clearance":"restricted"}`))
	}))
	defer server.Close()
	whoami := wikiWhoAmI(server.URL, server.Client())
	principal, status, err := whoami(context.Background(), "Bearer admin")
	if err != nil || status != http.StatusOK || principal != (Principal{Kind: "human", Role: "admin", Name: "alice", Identity: "opaque-alice"}) {
		t.Fatalf("%+v %d %v", principal, status, err)
	}
	if _, status, err := whoami(context.Background(), "Bearer forged"); err != nil || status != http.StatusUnauthorized {
		t.Fatalf("forged token: %d %v", status, err)
	}
	server.Close()
	if _, _, err := whoami(context.Background(), "Bearer admin"); err == nil {
		t.Fatal("an unreachable wikisvc authorized the caller")
	}
}

func TestTheDaemonListensOnlyOnTheSocketSystemdGivesIt(t *testing.T) {
	t.Setenv("LISTEN_PID", "1")
	t.Setenv("LISTEN_FDS", "1")
	if _, err := systemdListener(); err == nil {
		t.Fatal("accepted a socket passed to another process")
	}
}
