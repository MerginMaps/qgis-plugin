import xml.etree.ElementTree as ET  # nosec B405
from xml.etree.ElementTree import Element  # nosec B405
from typing import Dict
import zipfile


def _read_xml_tree_from_project(project_path: str) -> Element:
    if project_path.endswith(".qgs"):
        with open(project_path, "r", encoding="utf-8") as f:
            return ET.parse(f).getroot()  # nosec B314
    elif project_path.endswith(".qgz"):
        return _read_xml_tree_from_qgz(project_path)
    else:
        raise ValueError(f"Unsupported project file format: {project_path}")


def _read_xml_tree_from_qgz(qgz_path: str) -> Element:
    qgs_filename = next(
        (name for name in zipfile.ZipFile(qgz_path).namelist() if name.endswith(".qgs")),
        None,
    )

    if qgs_filename is None:
        raise ValueError(f"No .qgs file found inside {qgz_path}")

    with zipfile.ZipFile(qgz_path, "r") as input_zip_file:
        entries = {name: input_zip_file.read(name) for name in input_zip_file.namelist()}

    return ET.fromstring(entries[qgs_filename])  # nosec B314


def is_qgis_version_4(project_file: str) -> bool:
    root = _read_xml_tree_from_project(project_file)

    version = root.attrib.get("version", "")
    if not version.startswith("4."):
        return False

    return True


def _parse_properties(element, prefix="") -> Dict:
    """Recursively parse nested <properties> elements into a flat dict with path keys."""
    result = {}

    for child in element:
        if child.tag != "properties":
            continue

        name = child.attrib.get("name", "")
        key = f"{prefix}/{name}" if prefix else name
        prop_type = child.attrib.get("type")

        if prop_type is not None:
            if prop_type == "QStringList":
                result[key] = [v.text for v in child.findall("value")]
            else:
                result[key] = child.text
        else:
            result.update(_parse_properties(child, prefix=key))

    return result


def read_mergin_properties(project_file: str) -> Dict:
    root = _read_xml_tree_from_project(project_file)

    version = root.attrib.get("version", "")
    if not version.startswith("4."):
        return {}

    mergin_elem = root.find(".//properties[@name='Mergin']")
    if mergin_elem is None:
        return {}

    props = _parse_properties(mergin_elem)

    return props
