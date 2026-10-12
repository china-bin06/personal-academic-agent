import argparse
from pathlib import Path

import pdfplumber


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    source = Path(args.file)

    with pdfplumber.open(source) as pdf:
        print(f"页数：{len(pdf.pages)}")

        for index, page in enumerate(pdf.pages, start=1):
            print(f"\n第 {index} 页")

            text = page.extract_text() or ""
            print(text)

            tables = page.extract_tables()
            print(f"检测到表格：{len(tables)}")

            for table in tables:
                for row in table:
                    print(row)


if __name__ == "__main__":
    main()