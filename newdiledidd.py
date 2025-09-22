import pandas as pd
from itertools import combinations  # Not used now, but kept for fallback if needed
import logging
import sys
import hashlib  # For hashing fallback

# Step 0: Set up logging (change to DEBUG for more details)
logging.basicConfig(
    level=logging.INFO,  # Set to logging.DEBUG for verbose output
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('comparison.log'),  # Logs to file
        logging.StreamHandler(sys.stdout)       # Also logs to console
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
df1_common = df1[list(common_columns)]
df2_common = df2[list(common_columns)]
logger.info("Filtered dataframes to common columns.")

# Step 6: Heuristic auto-detect composite key (iterative addition for larger keys)
def find_composite_key(df, columns, max_cols=15):  # Increased max to 15; adjust as needed
    """Heuristic: Sort columns by uniqueness ratio, add one by one until unique combo found."""
    logger.info(f"Auto-detecting composite key from {len(columns)} columns (heuristic: iterative top uniques, up to {max_cols}).")
    
    # Compute unique ratios
    ratios = {}
    for col in columns:
        try:
            unique_count = df[col].nunique()
            ratios[col] = unique_count / len(df) if len(df) > 0 else 0
            logger.debug(f"Column '{col}': {unique_count} unique values (ratio: {ratios[col]:.2f})")
        except Exception as e:
            logger.warning(f"Skipping column '{col}' for ratio calc: {e}")
            ratios[col] = 0
    
    # Sort by descending ratio
    sorted_cols = sorted(ratios, key=ratios.get, reverse=True)
    logger.info(f"Top unique columns: {sorted_cols[:10]}")  # Show top 10 for insight
    
    # Start with empty combo, add columns iteratively until no duplicates
    current_combo = []
    for i, col in enumerate(sorted_cols[:max_cols]):
        current_combo.append(col)
        logger.info(f"Testing cumulative combo {i+1}: {current_combo}")
        try:
            if df[current_combo].duplicated().sum() == 0:
                logger.info(f"Found unique composite key after {len(current_combo)} columns: {current_combo}")
                return current_combo
        except Exception as e:
            logger.warning(f"Error testing {current_combo}: {e}; continuing to add columns.")
    
    # If still duplicates after max_cols, add more or fallback
    if df[current_combo].duplicated().sum() > 0:
        logger.warning(f"Still duplicates after top {max_cols} columns; adding next 5 to reach uniqueness.")
        for col in sorted_cols[max_cols:max_cols+5]:
            current_combo.append(col)
            logger.info(f"Adding extra column: {current_combo[-1]} (now {len(current_combo)} columns)")
            try:
                if df[current_combo].duplicated().sum() == 0:
                    logger.info(f"Found unique composite key after extra addition: {current_combo}")
                    return current_combo
            except Exception as e:
                logger.warning(f"Error with extra {col}: {e}; continuing.")
    
    logger.warning(f"Could not find unique combo within limits; using top {len(current_combo)} columns as fallback (may have duplicates).")
    return current_combo  # Fallback: top columns (even if not fully unique)

# Detect key from df1 (can use df2 if preferred; uses full data since rows are small)
composite_key = find_composite_key(df1_common, common_columns)
logger.info(f"Final auto-detected composite key: {composite_key}")

# Manual override option: Uncomment and set if needed
# composite_key = ['YourKeyCol1', 'YourKeyCol2']  # e.g., ['ID', 'Date']

# Step 7: Remove duplicates based on composite key (full data)
df1_common = df1_common.drop_duplicates(subset=composite_key, keep='first')
df2_common = df2_common.drop_duplicates(subset=composite_key, keep='first')
logger.info(f"After deduplication - file1: {len(df1_common)} rows, file2: {len(df2_common)} rows")

# Step 8: Log data types and sample for key columns
logger.info("Data types in composite key (file1):")
for col in composite_key:
    logger.info(f"  {col}: {df1_common[col].dtype}")
logger.info("Data types in composite key (file2):")
for col in composite_key:
    logger.info(f"  {col}: {df2_common[col].dtype}")

# Step 8: Perform outer merge on composite key (with fallback hashing)
try:
    merged_df = df1_common.merge(df2_common, how='outer', on=composite_key, indicator=True)
    logger.info("Merge completed successfully.")
except Exception as e:
    logger.error(f"Direct merge failed: {e}. Attempting fallback with hashed keys...")
    try:
        # Fallback: Create hash columns for keys (handles type mismatches/NaNs)
        def hash_row(row):
            key_str = '_'.join(str(val) for val in row[composite_key].values if pd.notna(val))
            return hashlib.md5(key_str.encode()).hexdigest()
        
        df1_common['key_hash'] = df1_common.apply(hash_row, axis=1)
        df2_common['key_hash'] = df2_common.apply(hash_row, axis=1)
        
        merged_df = df1_common.merge(df2_common, how='outer', left_on='key_hash', right_on='key_hash', indicator=True)
        # Drop hash column
        merged_df = merged_df.drop('key_hash', axis=1)
        logger.info("Fallback hash-based merge completed successfully.")
    except Exception as e2:
        logger.error(f"Fallback merge also failed: {e2}")
        sys.exit(1)

# Step 9: Filter for unique and matching records
unique_to_file1 = merged_df[merged_df['_merge'] == 'left_only'].drop('_merge', axis=1)
unique_to_file2 = merged_df[merged_df['_merge'] == 'right_only'].drop('_merge', axis=1)
matches = merged_df[merged_df['_merge'] == 'both'].drop('_merge', axis=1)

# Step 10: Save results
unique_to_file1.to_csv('unique_records_file1.csv', index=False)
unique_to_file2.to_csv('unique_records_file2.csv', index=False)
matches.to_csv('matching_records.csv', index=False)
with open('auto_key_summary.txt', 'w') as f:
    f.write(f"Auto-detected composite key: {composite_key}\n")
logger.info("Results saved: unique_records_file1.csv, unique_records_file2.csv, matching_records.csv, auto_key_summary.txt")

# Step 11: Summary (via logger)
logger.info(f"Columns unique to file1: {list(unique_to_file1)}")
logger.info(f"Columns unique to file2: {list(unique_to_file2)}")
logger.info(f"Common columns used for comparison: {list(common_columns)}")
logger.info(f"Auto-detected composite key: {composite_key}")
logger.info(f"Unique records in file1: {len(unique_to_file1)}")
logger.info(f"Unique records in file2: {len(unique_to_file2)}")
logger.info(f"Matching records: {len(matches)}")
logger.info("File comparison process completed successfully.")