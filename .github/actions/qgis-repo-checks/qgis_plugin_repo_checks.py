# GPLv3 license
# Copyright Lutra Consulting Limited

"""Mirror the security and style scan that plugins.qgis.org runs on every upload.

Exit status is 0 when nothing blocks, 1 when something does, 2 on a usage error.

The scan covers the plugin and the python-api-client bundled into it as Mergin/mergin.
That rule set (qgis_plugin_repo_rules.json) is a pinned snapshot -- refresh it from
https://github.com/qgis/QGIS-Plugins-Website/tree/master/qgis-app/plugins/management/commands/data
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_FILE = os.path.join(HERE, "qgis_plugin_repo_rules.json")

# Mirrors the rsync filter in the plugin's packages.yml, so we scan what actually
# ships. deps/ holds third-party wheels pulled at build time and is never in git.
EXCLUDED_DIRS = ["test", "__pycache__", ".ruff_cache", "deps"]

# Package directory to scan when none is given, by repository.
DEFAULT_ROOTS = ["Mergin", "mergin"]

# Extensions the repository's file analysis flags as suspicious.
SUSPICIOUS_EXTENSIONS = (".exe", ".dll", ".so", ".dylib", ".bat", ".sh", ".ps1", ".cmd")

MAX_LINE_LENGTH = 120


class Finding:
    def __init__(self, code, path, line, message, tool):
        self.code = code
        self.path = path
        self.line = line
        self.message = message
        self.tool = tool


def load_rules():
    with open(RULES_FILE) as f:
        return json.load(f)["rules"]


def enabled_codes(rules, category):
    return sorted(c for c, r in rules[category].items() if r["enabled"])


def is_mandatory(rules, category, code):
    rule = rules[category].get(code)
    if rule is None:
        # Only detect-secrets can report something outside the snapshot, because it
        # enables every detector it ships. Any finding blocks, so assume the worst.
        return category == "secrets"
    return not rule["can_be_skipped"]


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def check_bandit(root, rules):
    codes = enabled_codes(rules, "bandit")
    excludes = ",".join(os.path.join(root, d) for d in EXCLUDED_DIRS)
    result = run(["bandit", "-r", root, "-f", "json", "--quiet", "-x", excludes, "-t", ",".join(codes)])
    if not result.stdout.strip():
        sys.stderr.write(result.stderr)
        raise RuntimeError("bandit produced no output")
    findings = []
    for issue in json.loads(result.stdout).get("results", []):
        findings.append(
            Finding(
                issue.get("test_id", ""),
                issue.get("filename", ""),
                issue.get("line_number", 0),
                issue.get("issue_text", ""),
                "bandit",
            )
        )
    return findings


def check_secrets(root, rules):
    cmd = [
        "detect-secrets",
        "scan",
        "--all-files",
        # metadata.txt carries a commit SHA and the baseline stores hashed secrets;
        # the repository excludes both to avoid entropy false positives.
        "--exclude-files",
        r"metadata\.txt",
        "--exclude-files",
        r"\.secrets\.baseline",
    ]
    for directory in EXCLUDED_DIRS:
        cmd += ["--exclude-files", r"(^|/)%s/" % directory.replace(".", r"\.")]
    for code, rule in sorted(rules["secrets"].items()):
        if not rule["enabled"]:
            cmd += ["--disable-plugin", code]
    cmd.append(".")

    result = run(cmd, cwd=root)
    if not result.stdout.strip():
        sys.stderr.write(result.stderr)
        raise RuntimeError("detect-secrets produced no output")
    # detect-secrets reports a human label; map it back to the plugin class the rules use.
    by_label = {r["secret_type"]: code for code, r in rules["secrets"].items()}

    findings = []
    for path, secrets in json.loads(result.stdout).get("results", {}).items():
        if path.endswith((".pyc", ".pyo", ".so", ".dll", ".exe")):
            continue
        for secret in secrets:
            label = secret.get("type", "Unknown")
            findings.append(
                Finding(
                    by_label.get(label, label),
                    os.path.join(root, path),
                    secret.get("line_number", 0),
                    "Potential %s detected" % label,
                    "detect-secrets",
                )
            )
    return findings


def check_flake8(root, rules):
    codes = enabled_codes(rules, "flake8")
    cmd = [
        "flake8",
        # The repository never sees our pyproject.toml, so ignore local config.
        "--isolated",
        "--max-line-length=%d" % MAX_LINE_LENGTH,
        "--select=%s" % ",".join(codes),
        "--exclude=%s" % ",".join(EXCLUDED_DIRS),
        "--format=%(path)s\t%(row)d\t%(code)s\t%(text)s",
        root,
    ]
    result = run(cmd)
    findings = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        path, row, code, text = parts
        findings.append(Finding(code, path, int(row), text, "flake8"))
    return findings


def check_files(root, rules):
    findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if name.lower().endswith(SUSPICIOUS_EXTENSIONS):
                if rules["file_analysis"]["FILE_SUSPICIOUS"]["enabled"]:
                    findings.append(Finding("FILE_SUSPICIOUS", path, 0, "Executable or binary file", "file analysis"))
            elif name.endswith(".py") and os.access(path, os.X_OK):
                if rules["file_analysis"]["FILE_EXECUTABLE"]["enabled"]:
                    findings.append(
                        Finding("FILE_EXECUTABLE", path, 0, "Python file has executable permission", "file analysis")
                    )
            if name.startswith(".") and rules["file_analysis"]["FILE_HIDDEN"]["enabled"]:
                findings.append(Finding("FILE_HIDDEN", path, 0, "Hidden file", "file analysis"))
    return findings


def annotate(level, finding):
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    print(
        "::%s file=%s,line=%d,title=%s %s::%s"
        % (level, finding.path, max(finding.line, 1), finding.tool, finding.code, finding.message)
    )


def report(title, findings, rules, category, blocking):
    """Print one check's findings and return how many of them block the upload.

    Skippable findings count too: they only stop blocking if the uploader ticks that
    rule on the upload form, so treating them as passing would make a green run mean
    less than it appears to. The tag says which kind each one is, because that decides
    the fix -- a skippable finding can be accepted in place with `# nosec <code>` or
    `# pragma: allowlist secret`, both of which plugins.qgis.org honours.
    """
    if not findings:
        print("  %-16s no findings" % title)
        return 0
    mandatory = [f for f in findings if is_mandatory(rules, category, f.code)]
    print(
        "  %-16s %d finding(s): %d mandatory, %d skippable"
        % (title, len(findings), len(mandatory), len(findings) - len(mandatory))
    )
    for finding in findings:
        tag = "MANDATORY" if finding in mandatory else "skippable"
        print("    [%s] %s %s:%s %s" % (tag, finding.code, finding.path, finding.line or "-", finding.message))
        if blocking:
            annotate("error" if finding in mandatory else "warning", finding)
    return len(findings) if blocking else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "root", nargs="?", help="directory to scan (default: whichever of %s exists)" % "/".join(DEFAULT_ROOTS)
    )
    args = parser.parse_args()

    root = args.root or next((d for d in DEFAULT_ROOTS if os.path.isdir(d)), None)
    if not root:
        parser.error("no package directory given and none of %s found" % "/".join(DEFAULT_ROOTS))
    root = root.rstrip("/")
    if not os.path.isdir(root):
        parser.error("%s is not a directory" % root)

    rules = load_rules()

    print("QGIS plugin repository checks -- mirror of the plugins.qgis.org upload scan")
    print("Scanning %s as packaged (excluding %s)\n" % (root, ", ".join(EXCLUDED_DIRS)))

    print("Blocking checks (a single finding blocks the upload):")
    blockers = report("bandit", check_bandit(root, rules), rules, "bandit", True)
    blockers += report("detect-secrets", check_secrets(root, rules), rules, "secrets", True)

    print("\nInformational checks (reported on the plugin page, never block):")
    report("flake8", check_flake8(root, rules), rules, "flake8", False)
    report("file analysis", check_files(root, rules), rules, "file_analysis", False)

    if blockers:
        print("\n%d blocking finding(s) -- plugins.qgis.org would reject this upload." % blockers)
        print("Mandatory rules need a code change. Skippable ones can be accepted in place with")
        print("`# nosec <code>` or `# pragma: allowlist secret`, which the repository honours.")
        return 1
    print("\nNo blocking findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
