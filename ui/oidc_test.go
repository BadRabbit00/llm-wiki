package main

import (
	"bytes"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/go-jose/go-jose/v4"
)

type fakeOIDC struct {
	t                                     *testing.T
	idp, wiki                             *httptest.Server
	auth                                  *oidcAuth
	h                                     http.Handler
	key                                   *rsa.PrivateKey
	mu                                    sync.Mutex
	nonce, challenge, defect              string
	groups                                []string
	issuedGroups                          []string
	down                                  atomic.Bool
	discoveries, keyRequests, revocations atomic.Int64
	logs                                  bytes.Buffer
}

func oidcFixture(t *testing.T) *fakeOIDC {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	f := &fakeOIDC{t: t, key: key, groups: []string{"wiki-reviewers"}}
	f.idp = httptest.NewServer(http.HandlerFunc(f.identityProvider))
	f.idp.Config.ErrorLog = log.New(&f.logs, "", 0)
	f.wiki = httptest.NewServer(http.HandlerFunc(f.backend))
	t.Cleanup(f.idp.Close)
	t.Cleanup(f.wiki.Close)
	directory := t.TempDir()
	secret := filepath.Join(directory, "oidc.secret")
	issuerToken := filepath.Join(directory, "issuer.token")
	if err := os.WriteFile(secret, []byte("client-secret\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(issuerToken, []byte("issuer-secret\n"), 0600); err != nil {
		t.Fatal(err)
	}
	config := oidcConfig{Issuer: f.idp.URL, ClientID: "wiki", SecretFile: secret, SessionTokenFile: issuerToken,
		RedirectURL: "https://wiki.example/auth/callback", InsecureHTTP: true, CookieSecure: true}
	f.auth, err = newOIDC(config, f.wiki.URL)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(f.auth.close)
	base, err := handler(testFiles(), f.wiki.URL, f.wiki.URL)
	if err != nil {
		t.Fatal(err)
	}
	f.h = f.auth.protect(base)
	return f
}

func (f *fakeOIDC) identityProvider(w http.ResponseWriter, r *http.Request) {
	if f.down.Load() {
		http.Error(w, "unavailable", 503)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	switch r.URL.Path {
	case "/.well-known/openid-configuration":
		f.discoveries.Add(1)
		_ = json.NewEncoder(w).Encode(map[string]any{"issuer": f.idp.URL, "authorization_endpoint": f.idp.URL + "/authorize",
			"token_endpoint": f.idp.URL + "/token", "jwks_uri": f.idp.URL + "/keys", "end_session_endpoint": f.idp.URL + "/end-session",
			"id_token_signing_alg_values_supported": []string{"RS256"}})
	case "/keys":
		f.keyRequests.Add(1)
		f.mu.Lock()
		key := f.key
		f.mu.Unlock()
		_ = json.NewEncoder(w).Encode(jose.JSONWebKeySet{Keys: []jose.JSONWebKey{{Key: &key.PublicKey, KeyID: "key", Use: "sig", Algorithm: "RS256"}}})
	case "/token":
		if err := r.ParseForm(); err != nil {
			f.t.Error(err)
			w.WriteHeader(400)
			return
		}
		f.mu.Lock()
		nonce, challenge, defect, groups, key := f.nonce, f.challenge, f.defect, f.groups, f.key
		f.mu.Unlock()
		digest := sha256.Sum256([]byte(r.Form.Get("code_verifier")))
		if r.Method != "POST" || r.URL.RawQuery != "" || r.Form.Get("client_secret") != "client-secret" || r.Form.Get("client_id") != "wiki" ||
			r.Form.Get("redirect_uri") != "https://wiki.example/auth/callback" || base64.RawURLEncoding.EncodeToString(digest[:]) != challenge {
			f.t.Error("invalid confidential-client PKCE exchange")
			w.WriteHeader(400)
			return
		}
		claims := map[string]any{"iss": f.idp.URL, "aud": "wiki", "sub": "stable-subject", "preferred_username": "Alice",
			"nonce": nonce, "iat": time.Now().Unix(), "exp": time.Now().Add(time.Hour).Unix()}
		if groups != nil {
			claims["groups"] = groups
		}
		switch defect {
		case "nonce":
			claims["nonce"] = "other"
		case "issuer":
			claims["iss"] = "https://other.example"
		case "audience":
			claims["aud"] = "other-client"
		case "expired":
			claims["exp"] = time.Now().Add(-time.Second).Unix()
		case "future":
			claims["iat"] = time.Now().Add(2 * time.Minute).Unix()
		case "missing-iat":
			delete(claims, "iat")
		case "missing-exp":
			delete(claims, "exp")
		case "nbf":
			claims["nbf"] = time.Now().Add(2 * time.Minute).Unix()
		case "signature":
			key, _ = rsa.GenerateKey(rand.Reader, 2048)
		}
		payload, _ := json.Marshal(claims)
		signer, err := jose.NewSigner(jose.SigningKey{Algorithm: jose.RS256, Key: key}, (&jose.SignerOptions{}).WithType("JWT").WithHeader("kid", "key"))
		if err != nil {
			f.t.Error(err)
			return
		}
		signed, err := signer.Sign(payload)
		if err != nil {
			f.t.Error(err)
			return
		}
		raw, err := signed.CompactSerialize()
		if err != nil {
			f.t.Error(err)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"access_token": "idp-access-secret", "token_type": "Bearer", "id_token": raw})
	default:
		http.NotFound(w, r)
	}
}

func (f *fakeOIDC) backend(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Cookie") != "" {
		f.t.Error("browser cookies reached the backend")
	}
	if r.URL.Path == "/api/v1/sessions" && r.Method == "POST" {
		if r.Header.Get("Authorization") != "Bearer issuer-secret" {
			f.t.Error("missing issuer credential")
			w.WriteHeader(403)
			return
		}
		var input struct {
			Subject  string   `json:"subject"`
			Username string   `json:"username"`
			Groups   []string `json:"groups"`
		}
		if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
			f.t.Error(err)
			return
		}
		if input.Subject != "stable-subject" || input.Username != "Alice" || input.Groups == nil {
			f.t.Error("invalid session claims")
		}
		f.mu.Lock()
		f.issuedGroups = input.Groups
		f.mu.Unlock()
		_ = json.NewEncoder(w).Encode(map[string]any{"token": "human-session-secret", "expires_at": time.Now().Add(12 * time.Hour),
			"actor": map[string]string{"name": "Alice", "kind": "human"}})
		return
	}
	if r.Header.Get("Authorization") != "Bearer human-session-secret" || r.URL.Path == "/api/v1/expired" {
		w.WriteHeader(401)
		_, _ = w.Write([]byte("private upstream error"))
		return
	}
	if r.URL.Path == "/api/v1/sessions/current" && r.Method == "DELETE" {
		f.revocations.Add(1)
		w.WriteHeader(204)
		return
	}
	_, _ = w.Write([]byte(`{"name":"Alice","kind":"human","role":"reviewer","clearance":"restricted"}`))
}

func (f *fakeOIDC) request(method, path string, cookie *http.Cookie) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, "https://wiki.example"+path, nil)
	if cookie != nil {
		r.AddCookie(cookie)
	}
	if method != "GET" {
		r.Header.Set("Origin", "https://wiki.example")
	}
	w := httptest.NewRecorder()
	f.h.ServeHTTP(w, r)
	return w
}

func (f *fakeOIDC) begin() (string, *http.Cookie) {
	f.t.Helper()
	r := f.request("GET", "/", nil)
	if r.Code != 302 {
		f.t.Fatalf("login: %d %s", r.Code, r.Body.String())
	}
	address, _ := url.Parse(r.Header().Get("Location"))
	query := address.Query()
	if query.Get("code_challenge_method") != "S256" || query.Get("state") == "" || query.Get("nonce") == "" || query.Get("code_challenge") == "" {
		f.t.Fatal("login lacks PKCE/state/nonce")
	}
	f.mu.Lock()
	f.nonce = query.Get("nonce")
	f.challenge = query.Get("code_challenge")
	f.mu.Unlock()
	for _, cookie := range r.Result().Cookies() {
		if cookie.Name == flowCookie {
			return query.Get("state"), cookie
		}
	}
	f.t.Fatal("missing browser binding cookie")
	return "", nil
}

func sessionFrom(t *testing.T, response *httptest.ResponseRecorder) *http.Cookie {
	t.Helper()
	for _, cookie := range response.Result().Cookies() {
		if cookie.Name == sessionCookie {
			return cookie
		}
	}
	t.Fatal("missing session cookie")
	return nil
}

func TestOIDCCallbackAndCookieProxy(t *testing.T) {
	f := oidcFixture(t)
	state, binding := f.begin()
	response := f.request("GET", "/auth/callback?code=code&state="+state, binding)
	if response.Code != 302 {
		t.Fatalf("callback: %d %s", response.Code, response.Body.String())
	}
	cookie := sessionFrom(t, response)
	if !cookie.HttpOnly || !cookie.Secure || cookie.SameSite != http.SameSiteLaxMode || cookie.Path != "/" || !cookie.Expires.After(time.Now()) {
		t.Fatal("session cookie is not protected")
	}
	for _, endpoint := range []string{"/api/v1/whoami", "/agent-api/jobs"} {
		r := httptest.NewRequest("GET", endpoint, nil)
		r.AddCookie(cookie)
		r.Header.Set("Authorization", "Bearer issuer-secret")
		out := httptest.NewRecorder()
		f.h.ServeHTTP(out, r)
		if out.Code != 200 {
			t.Fatalf("proxy: %d", out.Code)
		}
		if strings.Contains(out.Body.String(), cookie.Value) {
			t.Fatal("session exposed to JavaScript")
		}
	}
	if strings.Contains(response.Body.String()+response.Header().Get("Location")+f.logs.String(), cookie.Value) {
		t.Fatal("session leaked")
	}
	if f.request("GET", "/auth/callback?code=code&state="+state, binding).Code != 400 {
		t.Fatal("state was reused")
	}
	if f.request("POST", "/api/v1/sessions", cookie).Code != 403 {
		t.Fatal("session response exposed through proxy")
	}
	unauthorized := f.request("GET", "/api/v1/expired", cookie)
	if unauthorized.Code != 302 || unauthorized.Header().Get("Location") != "/auth/login" || sessionFrom(t, unauthorized).MaxAge != -1 || unauthorized.Body.Len() != 0 {
		t.Fatal("401 did not discard cookie and redirect")
	}
}

func TestOIDCRejectsForeignExpiredOrUnboundState(t *testing.T) {
	f := oidcFixture(t)
	state, cookie := f.begin()
	for _, callback := range []struct {
		state  string
		cookie *http.Cookie
	}{{"foreign", cookie}, {state, nil}} {
		result := f.request("GET", "/auth/callback?code=code&state="+callback.state, callback.cookie)
		if result.Code != 400 || len(result.Result().Cookies()) != 0 {
			t.Fatal("invalid state accepted")
		}
	}
	f.auth.mu.Lock()
	flow := f.auth.flows[state]
	flow.expires = time.Now().Add(-time.Second)
	f.auth.flows[state] = flow
	f.auth.mu.Unlock()
	if f.request("GET", "/auth/callback?code=code&state="+state, cookie).Code != 400 {
		t.Fatal("expired flow accepted")
	}
}

func TestOIDCRejectsInvalidIDTokens(t *testing.T) {
	for _, defect := range []string{"nonce", "issuer", "audience", "expired", "future", "missing-iat", "missing-exp", "nbf", "signature"} {
		t.Run(defect, func(t *testing.T) {
			f := oidcFixture(t)
			f.defect = defect
			state, cookie := f.begin()
			result := f.request("GET", "/auth/callback?code=code&state="+state, cookie)
			if result.Code != 400 {
				t.Fatalf("invalid token accepted: %d", result.Code)
			}
			for _, value := range result.Result().Cookies() {
				if value.Name == sessionCookie {
					t.Fatal("invalid login received session")
				}
			}
		})
	}
}

func TestOIDCOutageAndLocalLogout(t *testing.T) {
	f := oidcFixture(t)
	if f.discoveries.Load() != 0 {
		t.Fatal("startup performed discovery")
	}
	f.down.Store(true)
	if f.request("GET", "/healthz", nil).Code != 200 {
		t.Fatal("health depends on IdP")
	}
	start := time.Now()
	if f.request("GET", "/auth/login", nil).Code != 503 || time.Since(start) > time.Second {
		t.Fatal("failed login did not degrade promptly")
	}
	cookie := &http.Cookie{Name: sessionCookie, Value: "human-session-secret"}
	if f.request("GET", "/api/v1/whoami", cookie).Code != 200 {
		t.Fatal("existing session depends on IdP")
	}
	f.down.Store(false)
	state, binding := f.begin()
	if f.request("GET", "/auth/callback?code=code&state="+state, binding).Code != 302 {
		t.Fatal("discovery did not retry")
	}
	f.down.Store(true)
	out := f.request("POST", "/auth/logout", cookie)
	if f.revocations.Load() != 1 || sessionFrom(t, out).MaxAge != -1 || out.Code != 303 {
		t.Fatal("IdP outage broke local logout")
	}
	if strings.Contains(out.Header().Get("Location"), cookie.Value) {
		t.Fatal("session leaked into logout URL")
	}
	if f.request("GET", "/auth/login", nil).Code != 503 {
		t.Fatal("cached discovery concealed an IdP outage")
	}
}

func TestOIDCMissingGroupsAndKeyCache(t *testing.T) {
	f := oidcFixture(t)
	f.groups = nil
	for range 2 {
		state, binding := f.begin()
		out := f.request("GET", "/auth/callback?code=code&state="+state, binding)
		if out.Code != 302 {
			t.Fatalf("login without groups: %d %s", out.Code, out.Body.String())
		}
	}
	if len(f.issuedGroups) != 0 || f.keyRequests.Load() != 1 {
		t.Fatal("missing groups or JWKS caching failed")
	}
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	f.mu.Lock()
	f.key = key
	f.mu.Unlock()
	state, binding := f.begin()
	if f.request("GET", "/auth/callback?code=code&state="+state, binding).Code != 302 || f.keyRequests.Load() != 2 {
		t.Fatal("key rotation failed")
	}
}

func TestOIDCRejectsMisconfigurationAndDoesNotFollowRedirects(t *testing.T) {
	f := oidcFixture(t)
	for _, changed := range []func(*oidcConfig){
		func(c *oidcConfig) { c.Issuer = "" }, func(c *oidcConfig) { c.ClientID = "" },
		func(c *oidcConfig) { c.SecretFile = "" }, func(c *oidcConfig) { c.InsecureHTTP = false },
		func(c *oidcConfig) { c.RedirectURL = "http://remote.example/auth/callback" },
	} {
		config := f.auth.config
		changed(&config)
		if auth, err := newOIDC(config, f.wiki.URL); err == nil {
			auth.close()
			t.Fatal("accepted invalid OIDC settings")
		}
	}
	targetCalls := atomic.Int64{}
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { targetCalls.Add(1) }))
	defer target.Close()
	redirect := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, target.URL, 302) }))
	defer redirect.Close()
	response, err := f.auth.client.Get(redirect.URL)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 302 || targetCalls.Load() != 0 || f.auth.client.Timeout != 10*time.Second {
		t.Fatal("outgoing request policy failed")
	}
	secure := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	defer secure.Close()
	secure.Config.ErrorLog = log.New(io.Discard, "", 0)
	if response, err := f.auth.client.Get(secure.URL); err == nil {
		response.Body.Close()
		t.Fatal("untrusted TLS certificate accepted")
	}
}

func TestOIDCCookieWritesRequireSameOrigin(t *testing.T) {
	f := oidcFixture(t)
	body := &watchedBody{}
	request := httptest.NewRequest("POST", "/api/v1/proposals", nil)
	request.Body = body
	request.AddCookie(&http.Cookie{Name: sessionCookie, Value: "human-session-secret"})
	request.Header.Set("Origin", "https://other.example")
	response := httptest.NewRecorder()
	f.h.ServeHTTP(response, request)
	if response.Code != 403 || body.read {
		t.Fatal("cross-origin write accepted or read")
	}
}
