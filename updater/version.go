package main

import (
	"regexp"
	"strconv"
)

// Channels an administrator can follow. Beta also sees releases: a release is newer
// than every beta of the same version, so beta moves on to it.
const (
	ChannelRelease = "release"
	ChannelBeta    = "beta"
)

// The same grammar scripts/check-release-tag.sh enforces before anything is published.
var tagPattern = regexp.MustCompile(`^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-beta\.(0|[1-9][0-9]*))?$`)

// Version is a release tag: vX.Y.Z, or vX.Y.Z-beta.N for a beta of that version.
type Version struct {
	Tag                 string
	Major, Minor, Patch int
	Beta                int // 0 for a release
	IsBeta              bool
}

func ParseVersion(tag string) (Version, bool) {
	match := tagPattern.FindStringSubmatch(tag)
	if match == nil {
		return Version{}, false
	}
	number := func(s string) (int, bool) {
		n, err := strconv.Atoi(s)
		return n, err == nil
	}
	v := Version{Tag: tag, IsBeta: match[4] != ""}
	ok := true
	for i, field := range []*int{&v.Major, &v.Minor, &v.Patch} {
		var good bool
		*field, good = number(match[i+1])
		ok = ok && good
	}
	if v.IsBeta {
		var good bool
		v.Beta, good = number(match[5])
		ok = ok && good
	}
	return v, ok
}

// Base is the version the code declares and /api/v1/health reports: X.Y.Z.
func (v Version) Base() string {
	return strconv.Itoa(v.Major) + "." + strconv.Itoa(v.Minor) + "." + strconv.Itoa(v.Patch)
}

// Less orders by semver precedence: X.Y.Z-beta.N < X.Y.Z.
func (v Version) Less(o Version) bool {
	for _, d := range [][2]int{{v.Major, o.Major}, {v.Minor, o.Minor}, {v.Patch, o.Patch}} {
		if d[0] != d[1] {
			return d[0] < d[1]
		}
	}
	if v.IsBeta != o.IsBeta {
		return v.IsBeta
	}
	return v.Beta < o.Beta
}

// Latest picks the newest tag the channel may install; other tags (main, sha-…) are ignored.
func Latest(tags []string, channel string) (Version, bool) {
	var best Version
	found := false
	for _, tag := range tags {
		v, ok := ParseVersion(tag)
		if !ok || (v.IsBeta && channel != ChannelBeta) {
			continue
		}
		if !found || best.Less(v) {
			best, found = v, true
		}
	}
	return best, found
}
