import http.server
import sqlite3
import json
import os

DB_PATH = os.path.expanduser('~/Downloads/db.sqlite')
PORT = 3000


def query_sourcing_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Raw material with most BOM usage among vitamin-d3 entries
    cur.execute("""
        SELECT p.Id, p.SKU, COUNT(DISTINCT bc.BOMId) AS bom_count
        FROM Product p
        JOIN BOM_Component bc ON bc.ConsumedProductId = p.Id
        WHERE p.SKU LIKE '%vitamin-d3%' AND p.Type = 'raw-material'
        GROUP BY p.Id
        ORDER BY bom_count DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    material_id = row['Id']
    material_sku = row['SKU']
    bom_count = row['bom_count']

    # Suppliers for this material
    cur.execute("""
        SELECT s.Name FROM Supplier_Product sp
        JOIN Supplier s ON sp.SupplierId = s.Id
        WHERE sp.ProductId = ?
    """, (material_id,))
    suppliers = [r['Name'] for r in cur.fetchall()]

    # Distinct brand companies that use this material
    cur.execute("""
        SELECT DISTINCT c.Name
        FROM BOM_Component bc
        JOIN BOM b ON bc.BOMId = b.Id
        JOIN Product fg ON b.ProducedProductId = fg.Id
        JOIN Company c ON fg.CompanyId = c.Id
        WHERE bc.ConsumedProductId = ?
    """, (material_id,))
    companies = [r['Name'] for r in cur.fetchall()]

    conn.close()

    # Parse human-readable name from SKU: RM-C30-vitamin-d3-cholecalciferol-<hash>
    parts = material_sku.split('-')
    name_parts = parts[2:-1]  # drop "RM", "C30", and trailing hash
    readable_name = ' '.join(p.capitalize() for p in name_parts)

    return {
        'material': {
            'id': material_id,
            'sku': material_sku,
            'name': readable_name,
            'bom_count': bom_count,
        },
        'suppliers': suppliers,
        'companies': companies,
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress request logs


if __name__ == '__main__':
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    # Write data.json once at startup so the static server can serve it
    data = query_sourcing_data()
    with open(os.path.join(base_dir, 'data.json'), 'w') as f:
        json.dump(data, f)
    print(f'data.json written ({data["material"]["bom_count"]} BOMs, {len(data["suppliers"])} suppliers)')

    with http.server.HTTPServer(('', PORT), Handler) as httpd:
        print(f'Agnes server running on http://localhost:{PORT}')
        httpd.serve_forever()
