import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from textblob import TextBlob
import os

class FileSummaryService:
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = None
        self.summary = {}

    def load_file(self):
        """Load CSV or XLSX file."""
        try:
            file_ext = os.path.splitext(self.file_path)[1].lower()
            if file_ext == '.csv':
                self.data = pd.read_csv(self.file_path)
            elif file_ext == '.xlsx':
                self.data = pd.read_excel(self.file_path)
            else:
                raise ValueError("Unsupported file format. Use CSV or XLSX.")
        except Exception as e:
            raise Exception(f"Error loading file: {str(e)}")

    def analyze_numerical_column(self, column):
        """Analyze a numerical column and return stats."""
        stats = {
            'mean': self.data[column].mean(),
            'median': self.data[column].median(),
            'std': self.data[column].std(),
            'min': self.data[column].min(),
            'max': self.data[column].max(),
            'missing': self.data[column].isna().mean() * 100
        }
        # Detect outliers using IQR
        Q1 = self.data[column].quantile(0.25)
        Q3 = self.data[column].quantile(0.75)
        IQR = Q3 - Q1
        outliers = self.data[column][(self.data[column] < (Q1 - 1.5 * IQR)) | (self.data[column] > (Q3 + 1.5 * IQR))].count()
        stats['outliers'] = outliers
        return stats

    def analyze_categorical_column(self, column):
        """Analyze a categorical or text column."""
        stats = {
            'unique_values': self.data[column].nunique(),
            'most_common': self.data[column].mode()[0] if not self.data[column].mode().empty else None,
            'missing': self.data[column].isna().mean() * 100
        }
        # Basic NLP for text columns (if string length suggests text)
        if self.data[column].dtype == 'object' and self.data[column].str.len().mean() > 10:
            try:
                text = ' '.join(self.data[column].dropna().astype(str))
                blob = TextBlob(text)
                stats['sentiment'] = {
                    'polarity': blob.sentiment.polarity,  # -1 (negative) to 1 (positive)
                    'subjectivity': blob.sentiment.subjectivity  # 0 (objective) to 1 (subjective)
                }
            except:
                stats['sentiment'] = 'Not enough text data for sentiment analysis'
        return stats

    def apply_clustering(self, numerical_columns, n_clusters=3):
        """Apply K-means clustering to numerical data."""
        try:
            if not numerical_columns:
                return None
            X = self.data[numerical_columns].dropna()
            if len(X) < n_clusters:
                return "Not enough data for clustering"
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            clusters = kmeans.fit_predict(X_scaled)
            return {
                'cluster_counts': pd.Series(clusters).value_counts().to_dict(),
                'cluster_centers': scaler.inverse_transform(kmeans.cluster_centers_).tolist()
            }
        except:
            return "Error performing clustering"

    def detect_anomalies(self, numerical_columns, contamination=0.1):
        """Detect anomalies in numerical data using Isolation Forest."""
        try:
            if not numerical_columns:
                return None
            X = self.data[numerical_columns].dropna()
            if len(X) < 2:
                return "Not enough data for anomaly detection"
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            iso_forest = IsolationForest(contamination=contamination, random_state=42)
            predictions = iso_forest.fit_predict(X_scaled)
            # Anomalies are labeled -1, normal points are 1
            anomaly_indices = self.data[numerical_columns].dropna().index[predictions == -1].tolist()
            return {
                'anomaly_count': len(anomaly_indices),
                'anomaly_indices': anomaly_indices
            }
        except:
            return "Error performing anomaly detection"

    def generate_summary(self, n_clusters=3, contamination=0.1):
        """Generate a summary of the file, including anomaly detection."""
        if self.data is None:
            self.load_file()

        self.summary['file_name'] = os.path.basename(self.file_path)
        self.summary['rows'] = len(self.data)
        self.summary['columns'] = len(self.data.columns)
        self.summary['column_details'] = {}

        # Analyze each column
        numerical_columns = self.data.select_dtypes(include=[np.number]).columns.tolist()
        categorical_columns = self.data.select_dtypes(include=['object', 'category']).columns.tolist()

        for col in self.data.columns:
            if col in numerical_columns:
                self.summary['column_details'][col] = self.analyze_numerical_column(col)
            else:
                self.summary['column_details'][col] = self.analyze_categorical_column(col)

        # Apply clustering and anomaly detection on numerical data
        self.summary['clustering'] = self.apply_clustering(numerical_columns, n_clusters)
        self.summary['anomalies'] = self.detect_anomalies(numerical_columns, contamination)

        return self.summary

    def print_summary(self):
        """Print the summary in a readable format, including anomalies."""
        summary = self.generate_summary()
        print(f"File Summary for: {summary['file_name']}")
        print(f"Rows: {summary['rows']}, Columns: {summary['columns']}")
        print("\nColumn Details:")
        for col, details in summary['column_details'].items():
            print(f"\nColumn: {col}")
            for key, value in details.items():
                if isinstance(value, float):
                    print(f"  {key}: {value:.2f}")
                else:
                    print(f"  {key}: {value}")
        if summary['clustering']:
            print("\nClustering Results:")
            print(f"  Cluster Counts: {summary['clustering']['cluster_counts']}")
            print(f"  Cluster Centers: {summary['clustering']['cluster_centers']}")
        if summary['anomalies']:
            print("\nAnomaly Detection Results:")
            print(f"  Anomaly Count: {summary['anomalies']['anomaly_count']}")
            print(f"  Anomaly Row Indices: {summary['anomalies']['anomaly_indices']}")

    def save_summary(self, output_path):
        """Save the summary to a JSON file."""
        import json
        with open(output_path, 'w') as f:
            json.dump(self.summary, f, indent=4)

if __name__ == "__main__":
    # Replace with the path to your CSV or XLSX file
    file_path = "sample_data.csv"  # Example: "C:/Users/YourName/Documents/sample_data.csv"
    service = FileSummaryService(file_path)
    try:
        service.print_summary()
        service.save_summary("summary.json")
    except Exception as e:
        print(f"Error: {str(e)}")