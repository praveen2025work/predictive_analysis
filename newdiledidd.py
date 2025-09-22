import pandas as pd
from itertools import combinations  # Not used now, but kept for fallback if needed
import logging
import sys

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

# Step 6: Heuristic auto-detect composite key (fast for many columns)
def find_composite_key(df, columns, max_cols=3):
    """Heuristic: Sort columns by uniqueness ratio, test top 1-3 cumulatively."""
    logger.info(f"Auto-detecting composite key from {len(columns)} columns (heuristic: top {max_cols} by uniqueness).")
    
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
    logger.info(f"Top unique columns: {sorted_cols[:5]}")  # Show top 5 for insight
    
    # Test cumulative top combos
    for r in range(1, min(max_cols, len(sorted_cols)) + 1):
        combo = sorted_cols[:r]
        logger.info(f"Testing top {r} columns as key: {combo}")
        try:
            if df[combo].duplicated().sum() == 0:
                logger.info(f"Found unique composite key: {combo}")
                return combo
        except Exception as e:
            logger.warning(f"Error testing {combo}: {e}; skipping.")
    
    logger.warning(f"No unique top-{max_cols} combo found; using all columns as fallback.")
    return list(columns)

# Detect key from df1 (can use df2 if preferred; uses full data since rows are small)
composite_key = find_composite_key(df1_common, common_columns)
logger.info(f"Final auto-detected composite key: {composite_key}")

# Step 7: Remove duplicates based on composite key (full data)
df1_common = df1_common.drop_duplicates(subset=composite_key, keep='first')
df2_common = df2_common.drop_duplicates(subset=composite_key, keep='first')
logger.info(f"After deduplication - file1: {len(df1_common)} rows, file2: {len(df2_common)} rows")

# Step 8: Perform outer merge on composite key
merged_df = df1_common.merge(df2_common, how='outer', on=composite_key, indicator=True)
logger.info("Merge completed.")

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