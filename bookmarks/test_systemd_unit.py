"""Checks on the systemd unit template shipped in ``etc/systemd/``."""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent
UNIT = REPO_ROOT / "etc" / "systemd" / "bunnify.service"

# What the repository-helpers `github-repo-lint` audit counts as sandboxing.
SANDBOXING_DIRECTIVES = (
    "CapabilityBoundingSet",
    "PrivateTmp",
    "ProtectHome",
    "ProtectSystem",
    "RestrictAddressFamilies",
)
# These need unprivileged user namespaces in a user unit, which some hosts
# disable or restrict, so the template deliberately leaves them out
# (see "Hardening" in docs/SYSTEMD.md).
NEEDS_USER_NAMESPACES = ("PrivateTmp", "PrivateUsers", "ProtectHome", "ProtectSystem")


def _parse(text: str) -> dict[str, dict[str, list[str]]]:
    """Return ``{section: {key: [values...]}}``; fail on any malformed line."""
    sections: dict[str, dict[str, list[str]]] = {}
    current: dict[str, list[str]] | None = None
    # A trailing backslash continues the assignment on the next line.
    text = re.sub(r"\\\n[ \t]*", " ", text)
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        key, separator, value = line.partition("=")
        if current is None or not separator or not key.strip():
            raise AssertionError(
                f"{UNIT.name}:{number}: not a section or Key=Value: {raw!r}"
            )
        current.setdefault(key.strip(), []).append(value.strip())
    return sections


# The spellings systemd's boolean parser accepts.
_TRUE = {"1", "on", "t", "true", "y", "yes"}
_FALSE = {"", "0", "f", "false", "n", "no", "off"}


def effective_families(values: list[str]) -> tuple[list[str], bool]:
    """Families left by repeated ``RestrictAddressFamilies=`` lines.

    Mirrors systemd's ``config_parse_address_families`` (v255): the lines
    accumulate; an empty assignment resets the list; a line that is exactly
    ``none`` (case-sensitive, and only as the whole value) resets it to an empty
    allow-list, which denies every family; a leading ``~`` makes a deny-list; and
    a word that is not an address family name is ignored with a warning, so
    ``AF_UNIX none`` is just ``AF_UNIX``.
    Returns ``(families, is_deny_list)``.
    """
    families: list[str] = []
    deny = False
    for value in values:
        text = value.strip()
        if not text or text == "none":
            families, deny = [], False
            continue
        tokens = text.split()
        if tokens[0].startswith("~"):
            deny = True
            tokens[0] = tokens[0][1:]
        families.extend(token for token in tokens if token.startswith("AF_"))
    return families, deny


def allows_server_network(values: list[str]) -> bool:
    """True when the effective policy still allows Unix, IPv4 and IPv6 sockets.

    The listener, the HTTPS calls to api.github.com and pypi.org and the
    health-check curl need all three. A deny-list is a different policy, so it
    is not accepted here.
    """
    families, deny = effective_families(values)
    return not deny and all(f in families for f in ("AF_UNIX", "AF_INET", "AF_INET6"))


def enabled_sandboxing(service: dict[str, list[str]]) -> list[str]:
    """Sandboxing directives that are really in effect (the last assignment wins)."""
    enabled: list[str] = []
    for name in SANDBOXING_DIRECTIVES:
        values = service.get(name)
        if not values:
            continue
        last = values[-1].strip().lower()
        if name == "PrivateTmp" and last in _TRUE:
            enabled.append(name)
        elif name in ("ProtectHome", "ProtectSystem") and last not in _FALSE:
            enabled.append(name)
        elif name == "RestrictAddressFamilies" and effective_families(values)[0]:
            enabled.append(name)
        elif name == "CapabilityBoundingSet":
            # systemd.exec(5): assigning the empty string resets the bounding set
            # to the *empty* set (every capability dropped); `CapabilityBoundingSet=~`
            # is the one that resets it to the full set. So any assignment other
            # than a bare "~" counts.
            if last != "~":
                enabled.append(name)
    return enabled


class ParserTests(SimpleTestCase):
    def test_a_trailing_backslash_continues_the_assignment(self) -> None:
        parsed = _parse(
            "[Service]\nRestrictAddressFamilies=AF_UNIX \\\n    AF_INET AF_INET6\n"
        )
        (value,) = parsed["Service"]["RestrictAddressFamilies"]
        self.assertEqual(["AF_UNIX", "AF_INET", "AF_INET6"], value.split())

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        parsed = _parse("# note\n\n[Service]\n; other\nNoNewPrivileges=true\n")
        self.assertEqual({"Service": {"NoNewPrivileges": ["true"]}}, parsed)


class SandboxingHelperTests(SimpleTestCase):
    def test_none_only_counts_as_the_whole_case_sensitive_value(self) -> None:
        # systemd compares the whole value with streq(), so these are not "none":
        # the word is not an address family and is ignored with a warning.
        self.assertEqual((["AF_UNIX"], False), effective_families(["AF_UNIX none"]))
        self.assertEqual((["AF_UNIX"], False), effective_families(["none AF_UNIX"]))
        self.assertEqual((["AF_UNIX"], False), effective_families(["AF_UNIX", "None"]))
        self.assertTrue(allows_server_network(["AF_UNIX AF_INET AF_INET6", "None"]))
        self.assertEqual(([], True), effective_families(["~none"]))

    def test_a_later_none_denies_every_family(self) -> None:
        self.assertEqual(([], False), effective_families(["AF_UNIX", "none"]))
        self.assertFalse(allows_server_network(["AF_UNIX AF_INET AF_INET6", "none"]))
        # ... and a list given after it applies again.
        self.assertTrue(
            allows_server_network(["none", "AF_UNIX AF_INET AF_INET6"]),
        )

    def test_the_network_policy_check_rejects_unusable_policies(self) -> None:
        self.assertTrue(allows_server_network(["AF_UNIX AF_INET AF_INET6"]))
        self.assertFalse(allows_server_network(["AF_UNIX AF_INET"]))  # no IPv6
        self.assertFalse(allows_server_network(["~AF_INET"]))  # a deny-list
        self.assertFalse(allows_server_network(["AF_UNIX AF_INET AF_INET6", ""]))

    def test_all_of_systemds_boolean_spellings_are_understood(self) -> None:
        for spelling in ("1", "on", "t", "true", "y", "yes", "YES"):
            self.assertEqual(
                ["PrivateTmp"], enabled_sandboxing({"PrivateTmp": [spelling]})
            )
        for spelling in ("0", "off", "f", "false", "n", "no", "NO"):
            self.assertEqual([], enabled_sandboxing({"PrivateTmp": [spelling]}))

    def test_a_disabled_directive_does_not_count(self) -> None:
        self.assertEqual([], enabled_sandboxing({"PrivateTmp": ["no"]}))
        self.assertEqual([], enabled_sandboxing({"ProtectSystem": ["no"]}))
        self.assertEqual(["PrivateTmp"], enabled_sandboxing({"PrivateTmp": ["yes"]}))

    def test_an_empty_restrict_address_families_resets_the_list(self) -> None:
        self.assertEqual(
            [], enabled_sandboxing({"RestrictAddressFamilies": ["AF_UNIX", ""]})
        )
        self.assertEqual(
            ["RestrictAddressFamilies"],
            enabled_sandboxing({"RestrictAddressFamilies": ["", "AF_UNIX"]}),
        )

    def test_repeated_restrict_address_families_lines_accumulate(self) -> None:
        self.assertEqual(
            (["AF_UNIX", "AF_INET", "AF_INET6"], False),
            effective_families(["AF_UNIX", "AF_INET AF_INET6"]),
        )
        self.assertEqual((["AF_INET"], True), effective_families(["~AF_INET"]))

    def test_an_empty_capability_bounding_set_counts_as_sandboxing(self) -> None:
        self.assertEqual(
            ["CapabilityBoundingSet"],
            enabled_sandboxing({"CapabilityBoundingSet": [""]}),
        )


class BunnifyUnitTests(SimpleTestCase):
    def setUp(self) -> None:
        self.unit = _parse(UNIT.read_text(encoding="utf-8"))
        self.service = self.unit["Service"]

    def test_the_unit_is_well_formed(self) -> None:
        self.assertEqual({"Unit", "Service", "Install"}, set(self.unit))
        self.assertIn("ExecStart", self.service)

    def test_no_new_privileges_is_enabled(self) -> None:
        values = self.service.get("NoNewPrivileges", [])
        self.assertTrue(values and values[-1].lower() in _TRUE, values)

    def test_at_least_one_sandboxing_directive_is_enabled(self) -> None:
        self.assertTrue(
            enabled_sandboxing(self.service),
            f"enable at least one of {', '.join(SANDBOXING_DIRECTIVES)}",
        )

    def test_the_server_can_still_listen_and_reach_the_network(self) -> None:
        values = self.service.get("RestrictAddressFamilies", [])
        self.assertTrue(values, "RestrictAddressFamilies is not set")
        self.assertTrue(allows_server_network(values), values)

    def test_directives_that_need_user_namespaces_stay_out_of_the_user_unit(
        self,
    ) -> None:
        present = [name for name in NEEDS_USER_NAMESPACES if name in self.service]
        self.assertEqual(
            [],
            present,
            "these need unprivileged user namespaces in a user unit and can fail "
            "with status=226/NAMESPACE; see 'Hardening' in docs/SYSTEMD.md",
        )

    def test_the_repo_dir_placeholder_is_still_there_for_setup_service(self) -> None:
        text = UNIT.read_text(encoding="utf-8")
        self.assertIn("@@REPO_DIR@@", text)
