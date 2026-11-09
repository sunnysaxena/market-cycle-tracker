
import re
from pathlib import Path

print("=== MySQL Schema Extractor ===")

source_text = input("Enter full path to Dump20260308.sql: ").strip()
source = Path(source_text.strip('"'))

if not source.is_file():
    raise FileNotFoundError(f"SQL dump not found: {source}")

output = Path("E:/market-cycle-tracker/docs/mysql_schema_only.sql")
output.parent.mkdir(parents=True, exist_ok=True)

create_table = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?",
    re.IGNORECASE
)

tables = []
inside_table = False
current_block = []

with source.open("r", encoding="utf-8-sig", errors="replace") as sql_file:
    for line in sql_file:
        if not inside_table:
            if create_table.match(line):
                inside_table = True
                current_block = [line]

                match = re.search(
                    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
                    line,
                    re.IGNORECASE
                )
                tables.append(match.group(1) if match else "Unknown")
        else:
            current_block.append(line)

            # Standard mysqldump CREATE TABLE closing line
            if line.lstrip().startswith(")") and ";" in line:
                with output.open(
                    "a" if output.exists() and tables[:-1] else "w",
                    encoding="utf-8"
                ) as out:
                    if len(tables) == 1:
                        out.write("-- Extracted MySQL table definitions\n\n")
                    out.writelines(current_block)
                    out.write("\n\n")

                inside_table = False
                current_block = []

if inside_table:
    print("WARNING: Last CREATE TABLE statement may be incomplete.")

print(f"\nTables found: {len(tables)}")
for table in tables:
    print(f" - {table}")

print(f"\nSchema output: {output}")
