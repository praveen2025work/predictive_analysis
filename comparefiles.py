import pandas as pd
import os
import re
import logging
import argparse
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('comparison.log'),
        logging.StreamHandler()  # Also log to console
    ]
)
logger = logging.getLogger(__name__)

def normalize_column(col):
    """
    Normalize a pandas Series: strip whitespace, replace 'NULL'/'null' with empty string.
    """
    col = col.astype(str).str.strip()
    col = col.replace({'NULL': '', 'null': ''})
    return col

def detect_pattern(series):
    """
    Detect a simple data pattern for a pandas Series.
    - EMPTY if blank
    - NUMERIC if all digits
    - NUMERIC_DECIMAL if digits with decimal or negative
    - ALPHANUMERIC if mix of letters, numbers, -, _, space
    - STRING otherwise
    """
    def classify(value):
        val = str(value).strip()
        if not val or val == 'nan':
            return "EMPTY"
        if re.fullmatch(r"^-?\d+$", val):
            return "NUMERIC"
        if re.fullmatch(r"^-?\d+(\.\d+)?$", val):
            return "NUMERIC_DECIMAL"
        if re.fullmatch(r"^[A-Za-z0-9\-_\s]+$", val):
            return "ALPHANUMERIC"
        return "STRING"
    return series.apply(classify)

def select_key_columns(df, n_keys):
    """
    Select top N columns with the highest number of unique values.
    """
    # After normalization, compute uniqueness
    uniqueness = df.nunique().sort_values(ascending=False)
    key_cols = uniqueness.head(n_keys).index.tolist()
    return key_cols

def compare_files(file_a, file_b, delimiter='|', sort_order='asc', key_column_count=None, output_dir='comparison_results'):
    """
    Compare two pipe-delimited files for data validation.
    
    Args:
        file_a (str): Path to file A (existing system).
        file_b (str): Path to file B (new system).
        delimiter (str): Delimiter, default '|'.
        sort_order (str): 'asc' or 'desc' for sorting.
        key_column_count (int, optional): Number of key columns. If None, use 10% of total.
        output_dir (str): Directory to save outputs.
    """
    logger.info(f"Starting comparison: {file_a} vs {file_b}")
    
    # Create output directory
    Path(output_dir).mkdir(exist_ok=True)
    logger.info(f"Output directory created/verified: {output_dir}")
    
    # Load files as string to preserve original data
    logger.info("Loading files...")
    df_a = pd.read_csv(file_a, delimiter=delimiter, dtype=str)
    df_b = pd.read_csv(file_b, delimiter=delimiter, dtype=str)
    logger.info(f"Loaded: {len(df_a)} rows in A, {len(df_b)} rows in B")
    
    # Normalize all columns: strip and handle NULL as empty
    logger.info("Normalizing columns...")
    df_a = df_a.apply(normalize_column)
    df_b = df_b.apply(normalize_column)
    logger.info("Normalization complete")
    
    # Check for structural differences
    if set(df_a.columns) != set(df_b.columns):
        missing_in_b = set(df_a.columns) - set(df_b.columns)
        extra_in_b = set(df_b.columns) - set(df_a.columns)
        logger.warning(f"Column structure mismatch: Missing in B: {missing_in_b}, Extra in B: {extra_in_b}")
        with open(f"{output_dir}/column_structure_differences.txt", 'w') as f:
            f.write("Column Structure Differences:\n")
            if missing_in_b:
                f.write(f"Columns missing in file B: {list(missing_in_b)}\n")
            if extra_in_b:
                f.write(f"Extra columns in file B: {list(extra_in_b)}\n")
        # Align to common columns for comparison
        common_cols = list(set(df_a.columns) & set(df_b.columns))
        df_a = df_a[common_cols]
        df_b = df_b[common_cols]
        logger.info(f"Using common columns: {common_cols}")
    else:
        logger.info("Column structures match")
    
    # Determine key columns based on uniqueness in file_a
    total_cols = len(df_a.columns)
    if key_column_count is None:
        key_column_count = max(1, int(total_cols * 0.1))  # 10% of total columns
    key_columns = select_key_columns(df_a, key_column_count)
    logger.info(f"Using key columns (top {key_column_count} by uniqueness): {key_columns}")
    
    # Sort both dataframes by key columns
    logger.info(f"Sorting data (order: {sort_order})...")
    ascending = sort_order.lower() == 'asc'
    sort_kwargs = {'by': key_columns, 'ascending': ascending if isinstance(ascending, bool) else [ascending] * len(key_columns)}
    df_a_sorted = df_a.sort_values(**sort_kwargs).reset_index(drop=True)
    df_b_sorted = df_b.sort_values(**sort_kwargs).reset_index(drop=True)
    logger.info("Sorting complete")
    
    # Prepare key data for indexing (use normalized keys, fill empty with '__BLANK__' for consistent hashing if needed)
    # But since empty '' is hashable and consistent after normalization, use as is
    df_a_indexed = df_a_sorted.set_index(key_columns)
    df_b_indexed = df_b_sorted.set_index(key_columns)
    logger.info("Indexing complete")
    
    # Identify extra/missing rows based on keys
    extra_in_a = df_a_indexed.index.difference(df_b_indexed.index)
    extra_in_b = df_b_indexed.index.difference(df_a_indexed.index)
    logger.info(f"Row differences: {len(extra_in_a)} extra in A, {len(extra_in_b)} extra in B")
    
    # Save extra rows (as pipe-delimited txt for consistency)
    if len(extra_in_a) > 0:
        df_a_indexed.loc[extra_in_a].reset_index().to_csv(f"{output_dir}/extra_rows_in_file_a.txt", sep='|', index=False)
        logger.info(f"Saved {len(extra_in_a)} extra rows from A")
    if len(extra_in_b) > 0:
        df_b_indexed.loc[extra_in_b].reset_index().to_csv(f"{output_dir}/extra_rows_in_file_b.txt", sep='|', index=False)
        logger.info(f"Saved {len(extra_in_b)} extra rows from B")
    
    # Align common rows
    common_idx = df_a_indexed.index.intersection(df_b_indexed.index)
    if len(common_idx) == 0:
        logger.error("No common rows found. Check key columns and data.")
        return
    
    logger.info(f"Found {len(common_idx)} common rows for detailed comparison")
    df_a_common = df_a_indexed.loc[common_idx]
    df_b_common = df_b_indexed.loc[common_idx]
    
    # Non-key columns for comparison
    compare_cols = [col for col in df_a_common.columns if col not in key_columns]
    logger.info(f"Comparing {len(compare_cols)} non-key columns")
    
    # Detect value mismatches (row-wise per column)
    value_mismatches = []
    logger.info("Detecting value mismatches...")
    with open(f"{output_dir}/column_value_mismatches.txt", 'w') as f:
        f.write("Row Index|Column|Mismatching Value in A|Mismatching Value in B\n")
        for col in compare_cols:
            diff_mask = df_a_common[col] != df_b_common[col]
            if diff_mask.any():
                num_mismatches = diff_mask.sum()
                logger.warning(f"Value mismatches in {col}: {num_mismatches} rows")
                mismatches = df_a_common[diff_mask]
                for idx, row in mismatches.iterrows():
                    val_a = row[col] if pd.notna(row[col]) and row[col] != '' else 'EMPTY'
                    val_b = df_b_common.loc[idx, col] if pd.notna(df_b_common.loc[idx, col]) and df_b_common.loc[idx, col] != '' else 'EMPTY'
                    f.write(f"{idx}|{col}|{val_a}|{val_b}\n")
                value_mismatches.append(col)
    logger.info(f"Value mismatch columns: {value_mismatches}")
    
    # Detect pattern mismatches
    pattern_mismatches = []
    logger.info("Detecting pattern mismatches...")
    with open(f"{output_dir}/column_pattern_mismatches.txt", 'w') as f:
        f.write("Row Index|Column|Pattern in A|Pattern in B|Value in A|Value in B\n")
        for col in compare_cols:
            pattern_a = detect_pattern(df_a_common[col])
            pattern_b = detect_pattern(df_b_common[col])
            diff_mask = pattern_a != pattern_b
            if diff_mask.any():
                num_mismatches = diff_mask.sum()
                logger.warning(f"Pattern mismatches in {col}: {num_mismatches} rows")
                mismatches = df_a_common[diff_mask]
                for idx, row in mismatches.iterrows():
                    val_a = row[col] if pd.notna(row[col]) and row[col] != '' else 'EMPTY'
                    val_b = df_b_common.loc[idx, col] if pd.notna(df_b_common.loc[idx, col]) and df_b_common.loc[idx, col] != '' else 'EMPTY'
                    f.write(f"{idx}|{col}|{pattern_a.loc[idx]}|{pattern_b.loc[idx]}|{val_a}|{val_b}\n")
                pattern_mismatches.append(col)
    logger.info(f"Pattern mismatch columns: {pattern_mismatches}")
    
    # Summary report
    total_rows_a = len(df_a_indexed)
    total_rows_b = len(df_b_indexed)
    common_rows = len(common_idx)
    
    # Count blanks in key columns for potential insight
    blank_keys_a = (df_a_sorted[key_columns] == '').all(axis=1).sum()
    blank_keys_b = (df_b_sorted[key_columns] == '').all(axis=1).sum()
    
    logger.info("Generating summary report...")
    with open(f"{output_dir}/summary_report.txt", 'w') as f:
        f.write("Comparison Summary\n")
        f.write("==================\n")
        f.write(f"Total rows in file A: {total_rows_a}\n")
        f.write(f"Total rows in file B: {total_rows_b}\n")
        f.write(f"Common rows: {common_rows}\n")
        f.write(f"Extra rows in file A: {len(extra_in_a)}\n")
        f.write(f"Extra rows in file B: {len(extra_in_b)}\n")
        f.write(f"Rows with all blank keys in A: {blank_keys_a}\n")
        f.write(f"Rows with all blank keys in B: {blank_keys_b}\n")
        f.write(f"Total columns: {total_cols}\n")
        f.write(f"Key columns used: {key_columns}\n")
        f.write(f"Columns with value mismatches: {value_mismatches}\n")
        f.write(f"Columns with pattern mismatches: {pattern_mismatches}\n")
        if 'missing_in_b' in locals():
            f.write(f"Columns missing in B: {list(missing_in_b)}\n")
        if 'extra_in_b' in locals():
            f.write(f"Extra columns in B: {list(extra_in_b)}\n")
        f.write("\nNote: Blanks/empties/NULLs have been normalized to empty strings for matching.\n")
        f.write("This ensures consistent treatment of missing data across files.\n")
    
    logger.info(f"✅ Comparison complete. Results saved in: {output_dir}")
    logger.info(f"📊 Summary: {len(extra_in_a)} extra in A, {len(extra_in_b)} extra in B, "
          f"{len(value_mismatches)} value mismatch columns, {len(pattern_mismatches)} pattern mismatch columns")
    logger.info(f"🔍 Blank key rows: {blank_keys_a} in A, {blank_keys_b} in B")
    
    print(f"✅ Comparison complete. Results saved in: {output_dir}")
    print(f"📊 Summary: {len(extra_in_a)} extra in A, {len(extra_in_b)} extra in B, "
          f"{len(value_mismatches)} value mismatch columns, {len(pattern_mismatches)} pattern mismatch columns")
    print(f"🔍 Blank key rows: {blank_keys_a} in A, {blank_keys_b} in B")
    print(f"📝 Logs saved to: comparison.log")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two pipe-delimited files.")
    parser.add_argument('--file_a', type=str, required=True, help="Path to file A (existing system)")
    parser.add_argument('--file_b', type=str, required=True, help="Path to file B (new system)")
    parser.add_argument('--delimiter', type=str, default='|', help="Delimiter (default: |)")
    parser.add_argument('--sort_order', type=str, default='asc', choices=['asc', 'desc'], help="Sort order")
    parser.add_argument('--key_column_count', type=int, default=None, help="Number of key columns (default: auto)")
    parser.add_argument('--output_dir', type=str, default='comparison_results', help="Output directory")
    
    args = parser.parse_args()
    
    compare_files(
        file_a=args.file_a,
        file_b=args.file_b,
        delimiter=args.delimiter,
        sort_order=args.sort_order,
        key_column_count=args.key_column_count,
        output_dir=args.output_dir
    )
