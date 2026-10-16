"""First-run check: report what time-capture still needs, as JSON.

Run: python preflight.py

Prints {"ready": bool, "missing": [...]}. Each entry has an `id`, what it
`unlocks`, and a `fix` the agent can run or hand to the user. Read-only.
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402


def _azure_state(cfg):
    if cfg.get("work_tracker", {}).get("kind") != "azure-devops":
        return []
    if not shutil.which("az"):
        return [{
            "id": "az-cli",
            "unlocks": "real work item titles and IDs instead of UNKNOWN",
            "fix": "Install the Azure CLI: https://aka.ms/installazurecli",
        }]
    out = []
    ext = subprocess.run(["az", "extension", "list", "-o", "json"],
                         capture_output=True, text=True, shell=os.name == "nt")
    if "azure-devops" not in (ext.stdout or ""):
        out.append({
            "id": "az-devops-extension",
            "unlocks": "work item lookup",
            "fix": "az extension add --name azure-devops",
        })
    acct = subprocess.run(["az", "account", "show"], capture_output=True,
                          text=True, shell=os.name == "nt")
    if acct.returncode != 0:
        out.append({
            "id": "az-login",
            "unlocks": "work item lookup",
            "fix": "az login (opens a browser, the user must complete it)",
        })
    return out


def main():
    missing = []
    cfg_file = _config.config_path()
    if not os.path.isfile(cfg_file):
        missing.append({
            "id": "config",
            "unlocks": "job matching, work hours, timesheet fill",
            "fix": "Create %s from config.example.json by asking the user for "
                   "their jobs, Azure DevOps org and timesheet URL" % cfg_file,
        })
    cfg = _config.load()
    if not shutil.which(cfg["sources"].get("ccrider_bin") or "ccrider"):
        missing.append({
            "id": "ccrider",
            "unlocks": "sessions from codex, copilot, opencode, pi, antigravity, amp",
            "fix": "Install https://github.com/neilberkman/ccrider "
                   "(skip if the user only uses Claude Code)",
        })
    missing.extend(_azure_state(cfg))
    print(json.dumps({"ready": not missing, "missing": missing}, indent=2))


if __name__ == "__main__":
    main()
