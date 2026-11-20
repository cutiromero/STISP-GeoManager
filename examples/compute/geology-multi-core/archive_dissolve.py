"""Dissolve only approved archive additions and their same-class edge neighbours."""

import json
from collections import defaultdict

import geopandas as gpd
from shapely import STRtree, get_parts, unary_union

EDGE_EPS_M = 1e-6
AREA_TOL_M2 = 0.01


def _edge_groups(parts, hosts):
    """Do not traverse existing host/host or point contacts."""
    tree = STRtree(hosts)
    by_part, by_host = defaultdict(dict), defaultdict(set)
    for index, part in enumerate(parts):
        for candidate in tree.query(part, predicate="intersects"):
            i = int(candidate)
            shared = part.boundary.intersection(hosts[i].boundary).length
            if shared > EDGE_EPS_M:
                by_part[index][i] = shared
                by_host[i].add(index)
    unseen = set(by_part)
    while unseen:
        pending = [min(unseen)]
        members, receivers = set(), set()
        while pending:
            p = pending.pop()
            if p in members:
                continue
            members.add(p)
            for h in by_part[p].keys() - receivers:
                receivers.add(h)
                pending.extend(by_host[h] - members)
        unseen.difference_update(members)
        yield sorted(members), sorted(receivers), by_part


def _class_coverage(rows):
    return unary_union([row["geometry"] for row in rows])


def _record_audit(records, components, removed_indices, rows, proof_tree, proofs):
    links = defaultdict(lambda: {"hosts": set(), "absorbed": set(), "removed": 0.0})
    for code, changes, keeper, absorbed, length in components:
        matched = []
        for position in proof_tree.query(changes, predicate="intersects"):
            index, targets = proofs[int(position)]
            if code not in targets:
                continue
            area = records[index]["_geometry"].intersection(changes).area
            if area <= 0:
                continue
            matched.append((area, index))
            links[index]["hosts"].add(str(rows[keeper]["feature_id"]))
            links[index]["absorbed"].update(
                str(rows[i]["feature_id"]) for i in absorbed & removed_indices
            )
        if not matched:
            raise ValueError("归档融合没有对应的冻结实际改类范围")
        # Count each removed edge only once. Other operations in the same
        # component still retain the IDs of their actual receiving features.
        _, responsible = min(
            matched, key=lambda match: (-match[0], str(records[match[1]]["feature_id"]))
        )
        links[responsible]["removed"] += length
    for index, audit in links.items():
        row = records[index]
        hosts = sorted(audit["hosts"])
        measurements = json.loads(row.get("measurements_json") or "{}")
        measurements["archive_dissolved_host_ids"] = hosts
        row.update(
            host_feature_id=hosts[0] if len(hosts) == 1 else "",
            absorbed_ids=json.dumps(sorted(audit["absorbed"]), ensure_ascii=False),
            removed_internal_boundary_m=audit["removed"],
            measurements_json=json.dumps(
                measurements, ensure_ascii=False, sort_keys=True
            ),
        )


def dissolve_archive_additions(frame, records):
    """Fuse an already validated partition without adding to its approved class mask.

    A-<class> features come from the archive operator's approved pixel masks;
    source features have frozen IDs. Only additions enter the search frontier.
    Audit records keep their original change geometry and area.
    """
    proofs = [
        (i, {value.strip() for value in row["new_code"].split("/") if value.strip()})
        for i, row in enumerate(records)
        if row["action"] == "reclassify" and row["actual_changed"]
    ]
    targets = set().union(*(codes for _, codes in proofs))
    if not targets:
        return frame
    rows = frame.to_dict("records")
    classes = defaultdict(list)
    for index, row in enumerate(rows):
        if row["geo_sym"] in targets:
            classes[row["geo_sym"]].append(index)
    updates, removals = {}, set()
    components = []
    for code in sorted(targets):
        indices = classes[code]
        additions = [i for i in indices if rows[i]["feature_id"] == "A-" + code]
        if not additions:
            # An approved candidate can include a target whose cells clip to no area.
            continue
        if len(additions) != 1:
            raise ValueError("归档融合需要每个实际改类类别的唯一新增面")
        addition = additions[0]
        host_parts = [
            (i, part)
            for i in indices
            if i != addition
            for part in get_parts(rows[i]["geometry"])
        ]
        host_geometry = [part for _, part in host_parts]
        parts = list(get_parts(rows[addition]["geometry"]))
        absorbed_parts, used_hosts = set(), set()
        updated_hosts = defaultdict(list)
        for members, receivers, edges in _edge_groups(parts, host_geometry):
            ordered = [parts[i] for i in members] + [
                host_geometry[i] for i in receivers
            ]
            merged = unary_union(ordered)
            weights = defaultdict(float)
            areas = defaultdict(float)
            for receiver in receivers:
                row_index, geom = host_parts[receiver]
                weights[row_index] += sum(edges[p].get(receiver, 0) for p in members)
                areas[row_index] += geom.area
            keep = min(
                weights,
                key=lambda h: (-weights[h], -areas[h], str(rows[h]["feature_id"])),
            )
            updated_hosts[keep].append(merged)
            used_hosts.update(receivers)
            absorbed_parts.update(members)
            removed = max(
                0.0, (sum(geometry.length for geometry in ordered) - merged.length) / 2
            )
            components.append(
                (
                    code,
                    unary_union([parts[i] for i in members]),
                    keep,
                    weights.keys() - {keep},
                    removed,
                )
            )
        if not absorbed_parts:
            continue
        touched = {host_parts[i][0] for i in used_hosts}
        for i, (host, part) in enumerate(host_parts):
            if host in touched and i not in used_hosts:
                updated_hosts[host].append(part)
        for host in touched:
            if updated_hosts[host]:
                updates[host] = {
                    **rows[host],
                    "geometry": unary_union(updated_hosts[host]),
                }
            else:
                removals.add(host)
        unmerged = [part for i, part in enumerate(parts) if i not in absorbed_parts]
        if unmerged:
            updates[addition] = {**rows[addition], "geometry": unary_union(unmerged)}
        else:
            removals.add(addition)
        old = [rows[i] for i in indices]
        new = [updates.get(i, rows[i]) for i in indices if i not in removals]
        old_union, new_union = _class_coverage(old), _class_coverage(new)
        if (
            old_union.symmetric_difference(new_union).area > AREA_TOL_M2
            or sum(r["geometry"].area for r in new) - new_union.area > AREA_TOL_M2
            or any(not row["geometry"].is_valid for row in new)
        ):
            raise ValueError("归档融合改变了实际获批类别范围或产生了拓扑错误")
    if not updates and not removals:
        return frame
    result = gpd.GeoDataFrame(
        [updates.get(i, row) for i, row in enumerate(rows) if i not in removals],
        columns=frame.columns,
        crs=frame.crs,
        geometry=frame.geometry.name,
    )
    if result.feature_id.duplicated().any():
        raise ValueError("归档融合产生了重复图斑编号")
    _record_audit(
        records,
        components,
        removals,
        rows,
        STRtree([records[i]["_geometry"] for i, _ in proofs]),
        proofs,
    )
    return result
