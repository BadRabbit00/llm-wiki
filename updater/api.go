// doc: MOD-updater.api

package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"
)

// Principal is the part of wikisvc's /api/v1/whoami the updater decides on.
// doc: DTO-updater.Principal
type Principal struct {
	Kind     string `json:"kind"`
	Role     string `json:"role"`
	Name     string `json:"name"`
	Identity string `json:"identity"`
}

// WhoAmI asks wikisvc who holds the bearer token: authorization stays in wikisvc,
// the updater only applies its rule. It returns the HTTP status wikisvc answered.
// doc: CLS-updater.WhoAmI
type WhoAmI func(ctx context.Context, authorization string) (Principal, int, error)

func wikiWhoAmI(base string, client *http.Client) WhoAmI {
	return func(ctx context.Context, authorization string) (Principal, int, error) {
		request, err := http.NewRequestWithContext(ctx, http.MethodGet, base+"/api/v1/whoami", nil)
		if err != nil {
			return Principal{}, 0, err
		}
		request.Header.Set("Authorization", authorization)
		response, err := client.Do(request)
		if err != nil {
			return Principal{}, 0, err
		}
		defer response.Body.Close()
		if response.StatusCode != http.StatusOK {
			return Principal{}, response.StatusCode, nil
		}
		var principal Principal
		if err := json.NewDecoder(response.Body).Decode(&principal); err != nil {
			return Principal{}, 0, err
		}
		return principal, http.StatusOK, nil
	}
}

type API struct {
	updater *Updater
	whoami  WhoAmI
}

func (a *API) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/status", a.admin(a.status))
	mux.HandleFunc("POST /v1/check", a.admin(a.check))
	mux.HandleFunc("PUT /v1/channel", a.admin(a.channel))
	mux.HandleFunc("POST /v1/apply", a.admin(a.apply))
	return mux
}

type principalKey struct{}

// admin lets through only a human administrator, the same rule wikisvc applies to
// every decision: replacing the running code is one.
// doc: CLS-updater.admin
func (a *API) admin(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		authorization := r.Header.Get("Authorization")
		if !strings.HasPrefix(strings.ToLower(authorization), "bearer ") || strings.TrimSpace(authorization[7:]) == "" {
			writeError(w, http.StatusUnauthorized, "E_UNAUTHORIZED", "Войдите в систему.")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
		defer cancel()
		principal, status, err := a.whoami(ctx, authorization)
		switch {
		case err != nil:
			writeError(w, http.StatusServiceUnavailable, "E_SERVICE_UNAVAILABLE", "Сервис вики недоступен; права проверить нельзя.")
		case status == http.StatusUnauthorized || status == http.StatusForbidden:
			writeError(w, http.StatusUnauthorized, "E_UNAUTHORIZED", "Войдите в систему.")
		case status != http.StatusOK:
			writeError(w, http.StatusServiceUnavailable, "E_SERVICE_UNAVAILABLE", "Сервис вики недоступен; права проверить нельзя.")
		case principal.Kind != "human":
			writeError(w, http.StatusForbidden, "E_HUMAN_REQUIRED", "Обновлять систему может только человек.")
		case principal.Role != "admin":
			writeError(w, http.StatusForbidden, "E_FORBIDDEN", "Обновлять систему может только администратор.")
		default:
			next(w, r.WithContext(context.WithValue(r.Context(), principalKey{}, principal)))
		}
	}
}

// doc: API-updater.status
func (a *API) status(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, a.updater.Status())
}

// doc: API-updater.check
func (a *API) check(w http.ResponseWriter, r *http.Request) {
	// A registry and signature check outlives an impatient client.
	ctx, cancel := context.WithTimeout(context.WithoutCancel(r.Context()), 2*time.Minute)
	defer cancel()
	if err := a.updater.Check(ctx); errors.Is(err, ErrBusy) {
		writeError(w, http.StatusConflict, "E_UPDATE_BUSY", "Проверка или обновление уже выполняется.")
		return
	}
	// Other failures are part of the status (check_error): the client shows them.
	writeJSON(w, http.StatusOK, a.updater.Status())
}

// doc: API-updater.channel
func (a *API) channel(w http.ResponseWriter, r *http.Request) {
	// doc: DTO-updater.ChannelRequest
	var body struct {
		Channel string `json:"channel"`
	}
	if !decode(w, r, &body) {
		return
	}
	switch err := a.updater.SetChannel(body.Channel); {
	case errors.Is(err, ErrChannel):
		writeError(w, http.StatusBadRequest, "E_UPDATE_CHANNEL", "Канал обновлений: release или beta.")
	case errors.Is(err, ErrBusy):
		writeError(w, http.StatusConflict, "E_UPDATE_BUSY", "Дождитесь окончания обновления.")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "E_UPDATE_STATE", "Не удалось сохранить настройку.")
	default:
		a.check(w, r)
	}
}

// doc: API-updater.apply
func (a *API) apply(w http.ResponseWriter, r *http.Request) {
	// doc: DTO-updater.ApplyRequest
	var body struct {
		Digest string `json:"digest"`
	}
	if !decode(w, r, &body) {
		return
	}
	principal := r.Context().Value(principalKey{}).(Principal)
	by := principal.Identity
	if by == "" {
		by = principal.Name
	}
	switch _, err := a.updater.Apply(body.Digest, by); {
	case errors.Is(err, ErrBusy):
		writeError(w, http.StatusConflict, "E_UPDATE_BUSY", "Проверка или обновление уже выполняется.")
	case errors.Is(err, ErrStale):
		writeError(w, http.StatusConflict, "E_UPDATE_STALE", "Предложенное обновление изменилось; проверьте обновления ещё раз.")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "E_UPDATE_STATE", "Не удалось начать обновление.")
	default:
		writeJSON(w, http.StatusAccepted, a.updater.Status())
	}
}

func decode(w http.ResponseWriter, r *http.Request, into any) bool {
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(into); err != nil {
		writeError(w, http.StatusBadRequest, "E_BAD_REQUEST", "Некорректный запрос.")
		return false
	}
	return true
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

// writeError uses wikisvc's error envelope so the interface reads both alike.
// doc: DTO-updater.Error
func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{
		"error": map[string]any{"code": code, "message": message, "hint": "", "details": nil},
	})
}
