"""Dependency-free structural checks; these do not replace Odoo integration tests.

Validates every FleetFlow addon (fleetflow and, when present, fleetflow_operations):
parses Python and XML, verifies manifest data/asset references exist, checks
intra-addon XML references and ACL rows, and confirms object-button methods
exist. External-module references are not resolved here (the Odoo install does).
"""
import ast
import csv
from pathlib import Path
import subprocess
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def _model_ids(addon):
    ids = set()
    for path in addon.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Name) and target.id == "_name"
                            and isinstance(node.value, ast.Constant)
                            and isinstance(node.value.value, str)):
                        ids.add("model_" + node.value.value.replace(".", "_"))
    return ids


def _methods(addon):
    methods = set()
    for path in addon.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        methods |= {n.name for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return methods


def check_addon(addon, strict_depends=None):
    module = addon.name
    manifest = ast.literal_eval((addon / "__manifest__.py").read_text(encoding="utf-8"))
    assert manifest["version"].startswith("16.0."), module
    if strict_depends is not None:
        assert set(manifest["depends"]) == strict_depends, (module, manifest["depends"])
    for rel in manifest.get("data", []):
        assert (addon / rel).is_file(), (module, rel)
    for assets in manifest.get("assets", {}).values():
        for asset in assets:
            assert (addon.parent / asset).is_file(), asset
    py_files = list(addon.rglob("*.py"))
    for path in py_files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    xml_files = list(addon.rglob("*.xml"))
    roots = [ET.parse(path).getroot() for path in xml_files]
    ids = set()
    for root in roots:
        for element in root.iter():
            if "id" in element.attrib:
                identifier = element.attrib["id"]
                assert identifier not in ids, (module, identifier)
                ids.add(identifier)
    ids |= _model_ids(addon)  # Odoo generates model_<name> ir.model records.
    for root in roots:
        for element in root.iter():
            for key in ("ref", "parent", "action"):
                ref = element.attrib.get(key)
                if not ref:
                    continue
                if "." not in ref:
                    assert ref in ids, (module, ref)
                elif ref.startswith(module + "."):
                    assert ref.split(".", 1)[1] in ids, (module, ref)
                # references to other installed modules are validated by Odoo.
    acl_path = addon / "security" / "ir.model.access.csv"
    acl_rows = 0
    if acl_path.is_file():
        with acl_path.open() as stream:
            for acl in csv.DictReader(stream):
                acl_rows += 1
                group = acl["group_id:id"]
                if "." not in group:
                    assert group in ids, (module, group)
                assert all(acl[k] in {"0", "1"}
                           for k in ("perm_read", "perm_write", "perm_create", "perm_unlink"))
    methods = _methods(addon)
    for root in roots:
        for button in root.iter("button"):
            if button.attrib.get("type") == "object":
                assert button.attrib["name"] in methods, (module, button.attrib["name"])
    for js in addon.rglob("static/src/**/*.js"):
        if shutil.which("node"):
            subprocess.run(["node", "--input-type=module", "--check"],
                           input=js.read_text(encoding="utf-8"), text=True, check=True)
    return module, len(py_files), len(xml_files), acl_rows


def main():
    results = [check_addon(ROOT / "custom_addons" / "fleetflow", {"web", "fleet", "mail"})]
    ops = ROOT / "custom_addons" / "fleetflow_operations"
    if ops.is_dir():
        results.append(check_addon(ops))
        depends = ast.literal_eval((ops / "__manifest__.py").read_text(encoding="utf-8"))["depends"]
        assert {"fleetflow", "fleet"} <= set(depends), depends
    assert ".env" in (ROOT / "fleetflow/.gitignore").read_text().splitlines(), "Ignore generated secrets."
    for module, npy, nxml, nacl in results:
        print(f"PASS {module}: {npy} Python files, {nxml} XML files, {nacl} ACL entries.")
    print("Odoo installation, database rules, browser behaviour and concurrency are NOT tested by this script.")


if __name__ == "__main__":
    main()
