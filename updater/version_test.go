package main

import "testing"

func TestParseVersionAcceptsWhatTheReleaseGuardAccepts(t *testing.T) {
	// The same tags tests/test_release_tag.py feeds scripts/check-release-tag.sh.
	for tag, valid := range map[string]bool{
		"v1.2.0": true, "v1.2.0-beta.3": true, "v1.3.0": true, "v0.0.1": true,
		"v1.2": false, "v01.2.0": false, "v1.2.0-rc.1": false, "1.2.0": false,
		"main": false, "sha-868f4a3": false, "v1.2.0-beta.03": false, "v1.2.0-beta": false,
	} {
		if _, ok := ParseVersion(tag); ok != valid {
			t.Errorf("ParseVersion(%q) valid = %v, want %v", tag, ok, valid)
		}
	}
}

func TestSemverPrecedence(t *testing.T) {
	ordered := []string{"v0.9.9", "v1.0.0-beta.1", "v1.0.0-beta.2", "v1.0.0-beta.10", "v1.0.0", "v1.0.1-beta.1", "v1.0.1", "v1.10.0"}
	for i := range ordered {
		for j := range ordered {
			a, _ := ParseVersion(ordered[i])
			b, _ := ParseVersion(ordered[j])
			if a.Less(b) != (i < j) {
				t.Errorf("%s < %s = %v, want %v", ordered[i], ordered[j], a.Less(b), i < j)
			}
		}
	}
}

func TestLatestPerChannel(t *testing.T) {
	tags := []string{"main", "sha-868f4a3", "v1.0.0", "v1.1.0-beta.2", "v1.1.0-beta.10", "v0.9.0"}
	if v, _ := Latest(tags, ChannelRelease); v.Tag != "v1.0.0" {
		t.Errorf("release channel picked %s", v.Tag)
	}
	if v, _ := Latest(tags, ChannelBeta); v.Tag != "v1.1.0-beta.10" {
		t.Errorf("beta channel picked %s", v.Tag)
	}
	if v, _ := Latest(append(tags, "v1.1.0"), ChannelBeta); v.Tag != "v1.1.0" {
		t.Errorf("beta channel did not move on to the release, picked %s", v.Tag)
	}
	if _, ok := Latest([]string{"main", "v1.0.0-beta.1"}, ChannelRelease); ok {
		t.Error("release channel offered a beta")
	}
	if v, _ := Latest(tags, ChannelRelease); v.Base() != "1.0.0" {
		t.Errorf("Base() = %s", v.Base())
	}
}
