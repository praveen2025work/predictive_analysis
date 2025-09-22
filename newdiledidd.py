import pandas as pd
import logging
import sys
import hashlib  # For hashing fallback

# Step 0: Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('comparison.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Step 1: Load the two files into dataframes
logger.info("Starting file comparison process.")
try:
    df1 = pd.read_csv('file1.csv')  # Replace with your file path/extension
    df2 = pd.read_csv('file2.csv')  # Replace with your file path/extension
    logger.info(f"Loaded file1: {len(df1)} rows, {len(df1.columns)} columns")
    logger.info(f"Loaded file2: {len(df2)} rows, {len(df2.columns)} columns")
except Exception as e:
    logger.error(f"Error loading files: {e}")
    sys.exit(1)

# Step 2: Identify unique and common columns
columns_file1 = set(df1.columns)
columns_file2 = set(df2.columns)
common_columns = columns_file1.intersection(columns_file2)
unique_to_file1 = columns_file1 - columns_file2
unique_to_file2 = columns_file2 - columns_file1

logger.info(f"Columns unique to file1: {list(unique_to_file1)}")
logger.info(f"Columns unique to file2: {list(unique_to_file2)}")
logger.info(f"Common columns: {list(common_columns)}")

# Step 3: Save column comparison results
with open('column_comparison.txt', 'w') as f:
    f.write(f"Columns unique to file1: {list(unique_to_file1)}\n")
    f.write(f"Columns unique to file2: {list(unique_to_file2)}\n")
    f.write(f"Common columns: {list(common_columns)}\n")
logger.info("Column comparison saved to column_comparison.txt")

# Step 4: Exit if no common columns
if not common_columns:
    logger.error("No common columns found. Cannot compare records.")
    sys.exit(1)

# Step 5: Filter dataframes to common columns
df1_common = df1[list(common_columns)].copy()
df2_common = df2[list(common_columns)].copy()
logger.info("Filtered dataframes to common columns.")

# Step 6: For full file matching, use ALL common columns as the "key" for row equality
composite_key = list(common_columns)  # Compare entire rows across all common columns
logger.info(f"Using all {len(composite_key)} common columns for full row matching.")

# Step 7: Standardize data types in key columns to avoid merge errors (coerce to string)
for col in composite_key:
    df1_common[col] = df1_common[col].astype(str)
    df2_common[col] = df2_common[col].astype(str)
logger.info("Standardized all columns to string for consistent merging.")

# Step 8: Remove duplicates based on all columns (full row uniqueness)
df1_common = df1_common.drop_duplicates(subset=composite_key, keep='first')
df2_common = df2_common.drop_duplicates(subset=composite_key, keep='first')
logger.info(f"After deduplication - file1: {len(df1_common)} rows, file2: {len(df2_common)} rows")

# Step 9: Log data types (now all string)
logger.info("All key columns standardized to object (string).")

# Step 10: Outer merge on all columns (full row comparison)
try:
    merged_df = df1_common.merge(df2_common, how='outer', on=composite_key, indicator=True, suffixes=('_file1', '_file2'))
    logger.info("Full row merge completed successfully.")
except Exception as e:
    logger.error(f"Merge failed: {e}. Using hash fallback...")
    try:
        # Fallback: Hash entire row
        def hash_row(row):
            row_str = '_'.join(str(val) for val in row[composite_key].values if pd.notna(val))
            return hashlib.md5(row_str.encode()).hexdigest()
        
        df1_common['row_hash'] = df1_common.apply(hash_row, axis=1)
        df2_common['row_hash'] = df2_common.apply(hash_row, axis=1)
        
        merged_df = df1_common.merge(df2_common, how='outer', left_on='row_hash', right_on='row_hash', indicator=True, suffixes=('_file1', '_file2'))
        merged_df = merged_df.drop('row_hash', axis=1)
        logger.info("Hash fallback merge succeeded.")
    except Exception as e2:
        logger.error(f"Fallback failed: {e2}")
        sys.exit(1)

# Step 11: Filter for non-matching records from file2 (unique to file2)
non_matching_file2 = merged_df[merged_df['_merge'] == 'right_only'].drop('_merge', axis=1)
# Clean up suffixes: Since full match, no need for suffixes in output
non_matching_file2.columns = [col.split('_file2')[0] if col.endswith('_file2') else col for col in non_matching_file2.columns]

# Step 12: Save the comparison file (non-matches from file2)
non_matching_file2.to_csv('non_matching_file2.csv', index=False)
with open('auto_key_summary.txt', 'w') as f:
    f.write(f"Full row comparison using {len(composite_key)} common columns.\n")
    f.write(f"Non-matching records from file2: {len(non_matching_file2)}\n")
logger.info(f"Comparison file saved: non_matching_file2.csv ({len(non_matching_file2)} rows)")
logger.info("Process completed.")