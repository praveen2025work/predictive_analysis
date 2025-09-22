import pandas as pd
import logging
import sys
import hashlib  # For hashing fallback
from itertools import combinations

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
df1_common = df1[list(common_columns)]
df2_common = df2[list(common_columns)]
logger.info("Filtered dataframes to common columns.")

# Step 6: Auto-detect composite key prioritizing low-cardinality combinations
def find_composite_key(df, columns, low_card_threshold=0.2, max_low_card=20, max_combo_size=3):
    """Auto-detect minimal unique combo: Prioritize low-cardinality columns (e.g., group, location).
    Test pairs/triples of low-card first, then fallback to high-unique iterative.
    """
    logger.info(f"Auto-detecting composite key from {len(columns)} columns.")
    
    # Identify low-cardinality columns (nunique / rows < threshold, e.g., 0.2 for groups/locations)
    low_card_ratios = {}
    for col in columns:
        try:
            unique_count = df[col].nunique()
            ratio = unique_count / len(df) if len(df) > 0 else 0
            if ratio < low_card_threshold:
                low_card_ratios[col] = ratio
        except Exception as e:
            logger.warning(f"Skipping '{col}': {e}")
    
    low_card_cols = sorted(low_card_ratios, key=low_card_ratios.get)[:max_low_card]  # Sort by ratio asc (lowest first)
    logger.info(f"Low-cardinality columns (threshold {low_card_threshold}): {low_card_cols[:10]}")  # Top 10
    
    # Test small combos of low-card first (pairs, then triples)
    for size in range(2, max_combo_size + 1):
        if len(low_card_cols) >= size:
            logger.info(f"Testing {size}-column combos from low-card columns...")
            for combo in combinations(low_card_cols, size):
                try:
                    if df[list(combo)].duplicated().sum() == 0:
                        logger.info(f"Found unique low-card combo: {list(combo)}")
                        return list(combo)
                except Exception as e:
                    logger.warning(f"Error testing {combo}: {e}")
    
    # Fallback: Iterative high-unique (as before)
    logger.info("No low-card unique combo; falling back to high-unique iterative.")
    high_ratios = {}
    for col in columns:
        try:
            unique_count = df[col].nunique()
            high_ratios[col] = unique_count / len(df) if len(df) > 0 else 0
        except:
            high_ratios[col] = 0
    sorted_high = sorted(high_ratios, key=high_ratios.get, reverse=True)
    logger.info(f"Top high-unique columns: {sorted_high[:10]}")
    current_combo = []
    for col in sorted_high[:15]:  # Limit to 15
        current_combo.append(col)
        try:
            if df[current_combo].duplicated().sum() == 0:
                logger.info(f"Heuristic found high-unique key: {current_combo}")
                return current_combo
        except Exception as e:
            logger.warning(f"Error in high-unique test: {e}")
    
    logger.warning("Fallback: Using all columns (may have duplicates).")
    return list(columns)

composite_key = find_composite_key(df1_common, common_columns)
logger.info(f"Final auto-detected composite key: {composite_key}")

# Step 7: Remove duplicates based on composite key
df1_common = df1_common.drop_duplicates(subset=composite_key, keep='first')
df2_common = df2_common.drop_duplicates(subset=composite_key, keep='first')
logger.info(f"After deduplication - file1: {len(df1_common)} rows, file2: {len(df2_common)} rows")

# Step 8: Log data types for key
for df_name, df in [("file1", df1_common), ("file2", df2_common)]:
    logger.info(f"Data types in key ({df_name}):")
    for col in composite_key:
        logger.info(f"  {col}: {df[col].dtype}")

# Step 9: Outer merge (with hash fallback)
try:
    merged_df = df1_common.merge(df2_common, how='outer', on=composite_key, indicator=True)
    logger.info("Merge completed.")
except Exception as e:
    logger.error(f"Merge failed: {e}. Using hash fallback...")
    try:
        def hash_row(row):
            return hashlib.md5('_'.join(str(val) for val in row[composite_key].values if pd.notna(val)).encode()).hexdigest()
        df1_common['key_hash'] = df1_common.apply(hash_row, axis=1)
        df2_common['key_hash'] = df2_common.apply(hash_row, axis=1)
        merged_df = df1_common.merge(df2_common, how='outer', left_on='key_hash', right_on='key_hash', indicator=True)
        merged_df = merged_df.drop('key_hash', axis=1)
        logger.info("Hash fallback merge succeeded.")
    except Exception as e2:
        logger.error(f"Fallback failed: {e2}")
        sys.exit(1)

# Step 10: Filter results
unique_to_file1 = merged_df[merged_df['_merge'] == 'left_only'].drop('_merge', axis=1)
unique_to_file2 = merged_df[merged_df['_merge'] == 'right_only'].drop('_merge', axis=1)
matches = merged_df[merged_df['_merge'] == 'both'].drop('_merge', axis=1)

# Step 11: Save and summarize
unique_to_file1.to_csv('unique_records_file1.csv', index=False)
unique_to_file2.to_csv('unique_records_file2.csv', index=False)
matches.to_csv('matching_records.csv', index=False)
with open('auto_key_summary.txt', 'w') as f:
    f.write(f"Composite key: {composite_key}\n")
logger.info(f"Results saved. Unique file1: {len(unique_to_file1)}, Unique file2: {len(unique_to_file2)}, Matches: {len(matches)}")
logger.info("Process completed.")