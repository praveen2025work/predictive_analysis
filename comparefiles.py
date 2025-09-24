import pandas as pd
import os
import re
import logging
import argparse
from pathlib import Path
from collections import Counter

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
    - NUMERIC if digits or decimal
    - ALPHANUMERIC if mix of letters, numbers, -, _, space
    - STRING otherwise
    """
    def classify(value):
        val = str(value).strip()
        if not val or val == 'nan':
            return "EMPTY"
        if re.fullmatch(r"^-?\d+(\.\d+)?$", val):
            return "NUMERIC"
        if re.fullmatch(r"^[A-Za-z0-9\-_\s]+$", val):
            return "ALPHANUMERIC"
        return "STRING"
    return series.apply(classify)

def get_pattern_dist(series):
    """
    Get normalized pattern distribution as dict.
    """
    patterns = detect_pattern(series)
    return patterns.value_counts(normalize=True).to_dict()

def select_key_columns(df, n_keys):
    """
    Select top N columns with the highest number of unique values.
    """
    # After normalization, compute uniqueness
    uniqueness = df.nunique().sort_values(ascending=False)
    key_cols = uniqueness.head(n_keys).index.tolist()
    return key_cols

def create_composite_key(df, key_columns):
    """
    Create a composite key by joining key column values with '|'.
    """
    df = df.copy()
    df['composite_key'] = df[key_columns].apply(lambda row: '|'.join(row.values.astype(str)), axis=1)
    return df

def compute_column_mapping(df_a, df_b):
    """
    Compute mapping from columns in A to best matching columns in B based on pattern similarity.
    """
    pattern_dists_a = {col: get_pattern_dist(df_a[col]) for col in df_a.columns}
    pattern_dists_b = {col: get_pattern_dist(df_b[col]) for col in df_b.columns}
    
    mapping = {}
    sim_scores = {}
    for col_a in df_a.columns:
        dist_a = pattern_dists_a[col_a]
        best_col = None
        best_sim = -1
        for col_b in df_b.columns:
            dist_b = pattern_dists_b[col_b]
            sim = sum(min(dist_a.get(p, 0), dist_b.get(p, 0)) for p in set(dist_a) | set(dist_b))
            if sim > best_sim:
                best_sim = sim
                best_col = col_b
        mapping[col_a] = best_col
        sim_scores[col_a] = best_sim
        logger.info(f"Column {col_a} mapped to {best_col} with similarity {best_sim:.2f}")
    
    return mapping, sim_scores

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
    
    total_cols = len(df_a.columns)
    
    # Compute column mapping based on pattern similarity
    logger.info("Computing column mappings...")
    mapping, sim_scores = compute_column_mapping(df_a, df_b)
    col_mapping_b_to_a = {v: k for k, v in mapping.items()}
    
    # Determine key columns based on uniqueness in file_a
    if key_column_count is None:
        key_column_count = max(1, int(total_cols * 0.1))  # 10% of total columns
    key_columns = select_key_columns(df_a, key_column_count)
    key_columns_b = [mapping[col] for col in key_columns]
    logger.info(f"Using key columns in A (top {key_column_count} by uniqueness): {key_columns}")
    logger.info(f"Corresponding key columns in B: {key_columns_b}")
    
    # Debug: Log sample unique values in key columns to identify mismatches
    logger.info("Debug: Sample unique values in key columns")
    for i, col in enumerate(key_columns):
        col_b = key_columns_b[i]
        sample_a = sorted(df_a[col].unique()[:10].tolist())
        sample_b = sorted(df_b[col_b].unique()[:10].tolist())
        logger.info(f"  {col} (A) / {col_b} (B) - A samples: {sample_a}")
        logger.info(f"  {col} (A) / {col_b} (B) - B samples: {sample_b}")
    
    # Create composite keys for both using mapped keys
    logger.info("Creating composite keys...")
    df_a_with_key = create_composite_key(df_a, key_columns)
    df_b_with_key = create_composite_key(df_b, key_columns_b)
    logger.info("Composite keys created")
    
    # Set index to composite key
    df_a_indexed = df_a_with_key.set_index('composite_key')
    df_b_indexed = df_b_with_key.set_index('composite_key')
    
    # Identify matching keys
    a_keys = set(df_a_indexed.index)
    b_keys = set(df_b_indexed.index)
    common_keys_set = a_keys.intersection(b_keys)
    extra_keys_in_a_set = a_keys - b_keys
    extra_keys_in_b_set = b_keys - a_keys
    
    common_keys = list(common_keys_set)
    extra_keys_in_a = list(extra_keys_in_a_set)
    extra_keys_in_b = list(extra_keys_in_b_set)
    
    logger.info(f"Key matches: {len(common_keys)} common, {len(extra_keys_in_a)} extra in A, {len(extra_keys_in_b)} extra in B")
    
    # Save extra rows based on keys
    if len(extra_keys_in_a) > 0:
        extra_a_df = df_a_indexed.loc[extra_keys_in_a].reset_index(drop=True)
        extra_a_df.to_csv(f"{output_dir}/extra_rows_in_file_a.txt", sep='|', index=False)
        logger.info(f"Saved {len(extra_keys_in_a)} extra rows from A")
    if len(extra_keys_in_b) > 0:
        extra_b_df = df_b_indexed.loc[extra_keys_in_b].reset_index(drop=True)
        extra_b_df.to_csv(f"{output_dir}/extra_rows_in_file_b.txt", sep='|', index=False)
        logger.info(f"Saved {len(extra_keys_in_b)} extra rows from B")
    
    use_key_alignment = len(common_keys) > 0
    common_rows = 0
    if use_key_alignment:
        alignment_method = "Key-based composite with mapping"
        # Get common keys in A's order
        a_keys_list = list(df_a_indexed.index)  # Ensure list
        common_keys_in_a_order = [k for k in a_keys_list if k in common_keys_set]
        df_a_common = df_a_indexed.loc[common_keys_in_a_order]
        df_b_matched = df_b_indexed.loc[common_keys_in_a_order]
        # Remap B columns to match A
        df_b_remapped = df_b_matched.rename(columns=col_mapping_b_to_a)
        # Reorder columns to match A
        df_b_remapped = df_b_remapped[df_a_common.columns]
        df_b_common = df_b_remapped
        # Reset indices
        df_a_common = df_a_common.reset_index(drop=True)
        df_b_common = df_b_common.reset_index(drop=True)
        common_rows = len(common_keys_in_a_order)
        # Save ordered B (aligned common rows, remapped)
        df_b_ordered = df_b_common.copy()
        df_b_ordered.to_csv(f"{output_dir}/ordered_file_b.txt", sep='|', index=False)
        logger.info(f"Saved ordered file B with {common_rows} aligned rows")
    else:
        logger.warning("No common keys found. Falling back to sequential alignment after sorting with mapping.")
        alignment_method = "Sequential fallback with mapping"
        ascending = sort_order.lower() == 'asc'
        all_cols_a = df_a.columns.tolist()
        all_cols_b = [mapping[col] for col in all_cols_a]
        df_a_sorted = df_a.sort_values(by=all_cols_a, ascending=ascending).reset_index(drop=True)
        df_b_sorted = df_b.sort_values(by=all_cols_b, ascending=ascending).reset_index(drop=True)
        common_rows = min(len(df_a_sorted), len(df_b_sorted))
        df_a_common = df_a_sorted.iloc[:common_rows].copy()
        # Remap B
        df_b_matched = df_b_sorted.iloc[:common_rows].copy()
        df_b_remapped = df_b_matched[all_cols_b].rename(columns={mapping[col]: col for col in all_cols_a})
        df_b_common = df_b_remapped
        # Save ordered B
        df_b_ordered = df_b_common.copy()
        df_b_ordered.to_csv(f"{output_dir}/ordered_file_b.txt", sep='|', index=False)
        logger.info(f"Saved ordered file B with {common_rows} aligned rows")
    
    logger.info(f"Found {common_rows} common rows for detailed comparison")
    
    # Non-key columns for comparison
    compare_cols = [col for col in df_a_common.columns if col not in key_columns]
    logger.info(f"Comparing {len(compare_cols)} non-key columns (using mapped columns)")
    
    # Detect value mismatches (row-wise per column)
    value_mismatches = []
    logger.info("Detecting value mismatches...")
    with open(f"{output_dir}/column_value_mismatches.txt", 'w') as f:
        f.write("Row Index|Column|Mismatching Value in A|Mismatching Value in B\n")
        for col in compare_cols:
            diff_mask = df_a_common[col] != df_b_common[col]
            if diff_mask.any():
                num_mismatches = diff_mask.sum()
                orig_b_col = next((k for k, v in mapping.items() if v == col), col)
                logger.warning(f"Value mismatches in {col} (B orig: {orig_b_col}): {num_mismatches} rows")
                mismatch_indices = list(diff_mask[diff_mask].index)
                for idx in mismatch_indices:
                    val_a = df_a_common.loc[idx, col] if pd.notna(df_a_common.loc[idx, col]) and df_a_common.loc[idx, col] != '' else 'EMPTY'
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
                orig_b_col = next((k for k, v in mapping.items() if v == col), col)
                logger.warning(f"Pattern mismatches in {col} (B orig: {orig_b_col}): {num_mismatches} rows")
                mismatch_indices = list(diff_mask[diff_mask].index)
                for idx in mismatch_indices:
                    val_a = df_a_common.loc[idx, col] if pd.notna(df_a_common.loc[idx, col]) and df_a_common.loc[idx, col] != '' else 'EMPTY'
                    val_b = df_b_common.loc[idx, col] if pd.notna(df_b_common.loc[idx, col]) and df_b_common.loc[idx, col] != '' else 'EMPTY'
                    f.write(f"{idx}|{col}|{pattern_a.loc[idx]}|{pattern_b.loc[idx]}|{val_a}|{val_b}\n")
                pattern_mismatches.append(col)
    logger.info(f"Pattern mismatch columns: {pattern_mismatches}")
    
    # Summary report
    total_rows_a = len(df_a)
    total_rows_b = len(df_b)
    
    # Count blanks in key columns for potential insight (if keys used)
    blank_keys_a = 0
    blank_keys_b = 0
    if use_key_alignment and key_columns:
        blank_keys_a = (df_a[key_columns] == '').all(axis=1).sum()
        blank_keys_b = (df_b[key_columns_b] == '').all(axis=1).sum()
    
    logger.info("Generating summary report...")
    with open(f"{output_dir}/summary_report.txt", 'w') as f:
        f.write("Comparison Summary\n")
        f.write("==================\n")
        f.write(f"Total rows in file A: {total_rows_a}\n")
        f.write(f"Total rows in file B: {total_rows_b}\n")
        f.write(f"Alignment method: {alignment_method}\n")
        f.write(f"Common/aligned rows: {common_rows}\n")
        f.write(f"Extra rows in file A: {len(extra_keys_in_a)}\n")
        f.write(f"Extra rows in file B: {len(extra_keys_in_b)}\n")
        if use_key_alignment and key_columns:
            f.write(f"Rows with all blank keys in A: {blank_keys_a}\n")
            f.write(f"Rows with all blank keys in B: {blank_keys_b}\n")
        f.write(f"Total columns: {total_cols}\n")
        f.write(f"Key columns used in A: {key_columns}\n")
        f.write(f"Key columns used in B: {key_columns_b}\n")
        f.write(f"Columns with value mismatches: {value_mismatches}\n")
        f.write(f"Columns with pattern mismatches: {pattern_mismatches}\n")
        f.write("Column Mappings (A -> B, similarity):\n")
        for col_a, col_b in mapping.items():
            sim = sim_scores[col_a]
            f.write(f"  {col_a} -> {col_b} ({sim:.2f})\n")
        if 'missing_in_b' in locals():
            f.write(f"Columns missing in B: {list(missing_in_b)}\n")
        if 'extra_in_b' in locals():
            f.write(f"Extra columns in B: {list(extra_in_b)}\n")
        f.write("\nNote: Blanks/empties/NULLs have been normalized to empty strings for matching.\n")
        f.write("This ensures consistent treatment of missing data across files.\n")
        f.write(f"Ordered file B saved: {output_dir}/ordered_file_b.txt\n")
        if not use_key_alignment:
            f.write("\nWarning: Used sequential alignment due to no key matches. Results may include false positives if row order differs.\n")
    
    logger.info(f"✅ Comparison complete. Results saved in: {output_dir}")
    logger.info(f"📊 Summary: {len(extra_keys_in_a)} extra in A, {len(extra_keys_in_b)} extra in B, "
          f"{len(value_mismatches)} value mismatch columns, {len(pattern_mismatches)} pattern mismatch columns")
    if use_key_alignment and key_columns:
        logger.info(f"🔍 Blank key rows: {blank_keys_a} in A, {blank_keys_b} in B")
    
    print(f"✅ Comparison complete. Results saved in: {output_dir}")
    print(f"📊 Summary: {len(extra_keys_in_a)} extra in A, {len(extra_keys_in_b)} extra in B, "
          f"{len(value_mismatches)} value mismatch columns, {len(pattern_mismatches)} pattern mismatch columns")
    if use_key_alignment and key_columns:
        print(f"🔍 Blank key rows: {blank_keys_a} in A, {blank_keys_b} in B")
    print(f"📝 Logs saved to: comparison.log")
    print(f"📄 Ordered file B: {output_dir}/ordered_file_b.txt")
    if not use_key_alignment:
        print("⚠️ Used sequential fallback alignment - check logs for key samples to improve key selection.")
    if len(common_keys) == 0:
        print("🔍 No key matches found. Review 'Debug: Sample unique values' in logs to see differences in key columns.")
        print("   Since column names match, mismatches likely due to data variations (e.g., formatting, extra chars).")

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
