import pandas as pd
from itertools import combinations

# Step 1: Load the two files into dataframes
df1 = pd.read_csv('file1.csv')  # Replace with your file path/extension
df2 = pd.read_csv('file2.csv')  # Replace with your file path/extension

# Step 2: Identify unique and common columns
columns_file1 = set(df1.columns)
columns_file2 = set(df2.columns)
common_columns = columns_file1.intersection(columns_file2)
unique_to_file1 = columns_file1 - columns_file2
unique_to_file2 = columns_file2 - columns_file1

# Step 3: Save column comparison results
with open('column_comparison.txt', 'w') as f:
    f.write(f"Columns unique to file1: {list(unique_to_file1)}\n")
    f.write(f"Columns unique to file2: {list(unique_to_file2)}\n")
    f.write(f"Common columns: {list(common_columns)}\n")

# Step 4: Exit if no common columns
if not common_columns:
    print("No common columns found. Cannot compare records.")
    exit()

# Step 5: Filter dataframes to common columns
df1_common = df1[list(common_columns)]
df2_common = df2[list(common_columns)]

# Step 6: Auto-detect composite key (minimal set of columns that uniquely identify rows)
def find_composite_key(df, columns):
    """Find the smallest set of columns where combined values are unique (no duplicates)."""
    for r in range(1, len(columns) + 1):
        for combo in combinations(columns, r):
            if df[list(combo)].duplicated().sum() == 0:  # No duplicates in this combo
                return list(combo)
    return list(columns)  # Fallback: all columns

# Detect key from df1 (can use df2 if preferred)
composite_key = find_composite_key(df1_common, common_columns)
print(f"Auto-detected composite key: {composite_key}")

# Step 7: Remove duplicates based on composite key
df1_common = df1_common.drop_duplicates(subset=composite_key, keep='first')
df2_common = df2_common.drop_duplicates(subset=composite_key, keep='first')

# Step 8: Perform outer merge on composite key
merged_df = df1_common.merge(df2_common, how='outer', on=composite_key, indicator=True)

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

# Step 11: Print summary
print(f"Columns unique to file1: {list(unique_to_file1)}")
print(f"Columns unique to file2: {list(unique_to_file2)}")
print(f"Common columns used for comparison: {list(common_columns)}")
print(f"Auto-detected composite key: {composite_key}")
print(f"Unique records in file1: {len(unique_to_file1)}")
print(f"Unique records in file2: {len(unique_to_file2)}")
print(f"Matching records: {len(matches)}")