import sqlite3
from types import SimpleNamespace

from apps.catalog import vector_store


def test_reads_only_confirmed_symbols_for_requested_unique_features(
    tmp_path, monkeypatch
):
    path = tmp_path / "vectors.gpkg"
    layer = 'confirmed"units'
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE gpkg_contents (table_name, data_type)")
        conn.execute("INSERT INTO gpkg_contents VALUES (?, 'features')", (layer,))
        conn.execute(
            'CREATE TABLE "confirmed""units" (feature_id, geo_sym, display_symbol, name, geom)'
        )
        conn.executemany(
            'INSERT INTO "confirmed""units" VALUES (?, ?, ?, ?, NULL)',
            [
                ("F00188", "U036", "γδπT₃", "花岗闪长质片麻岩"),
                ("F00221", "U034", "Pt₁Jgn", "角闪斜长片麻岩"),
                ("duplicate", "U036", "γδπT₃", "花岗闪长质片麻岩"),
                ("duplicate", "U034", "Pt₁Jgn", "角闪斜长片麻岩"),
            ],
        )
    monkeypatch.setattr(vector_store, "vector_geopackage_path", lambda: path)
    res = SimpleNamespace(data_type="vector", storage_path=layer)
    assert vector_store.feature_display_attributes(
        res, ["F00188", "duplicate", "not found"]
    ) == {
        "F00188": {
            "geo_sym": "U036",
            "display_symbol": "γδπT₃",
            "name": "花岗闪长质片麻岩",
        },
    }
