# ---------- Step 1: Imports ----------
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.datasets import make_blobs
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.metrics import silhouette_score
import scipy.cluster.hierarchy as sch

# ---------- Step 2: Synthetic data (4 blobs) ----------
# Generate 300 points around 4 centers
X, _ = make_blobs(n_samples=300, centers=4, cluster_std=0.60, random_state=42)
# Plot raw data
plt.scatter(X[:, 0], X[:, 1], s=30, c="blue")
plt.title("Synthetic data for clustering")
plt.show()

# ---------- Step 3: Elbow method ----------
inertia = []
# Try K from 1 to 10
for k in range(1, 11):
    km = KMeans(n_clusters=k, random_state=42)
    km.fit(X)
    inertia.append(km.inertia_)  # Store WCSS for each K

# Plot inertia vs K; the "elbow" suggests best K
plt.plot(range(1, 11), inertia, "bo-")
plt.xlabel("Number of clusters (K)")
plt.ylabel("Inertia (WCSS)")
plt.title("Elbow Method")
plt.show()

# ---------- Step 4: K-Means with K = 4 ----------
# Fit K-Means and get cluster labels
kmeans = KMeans(n_clusters=4, random_state=42)
y_kmeans = kmeans.fit_predict(X)

# Plot clusters colored by label
plt.scatter(X[:, 0], X[:, 1], c=y_kmeans, s=30, cmap="viridis")
# Overlay the centroids
plt.scatter(kmeans.cluster_centers_[:, 0], kmeans.cluster_centers_[:, 1],
            c="red", marker="X", s=200, label="Centroids")
plt.title("K-Means Clustering (K=4)")
plt.legend()
plt.show()

# ---------- Step 5: Silhouette score ----------
# Higher score (closer to 1) = better-separated clusters
score = silhouette_score(X, y_kmeans)
print(f"Silhouette score for K=4: {score:.3f}")  # about 0.876 in the demo

# ---------- Step 6: Dendrogram (Ward linkage) ----------
plt.figure(figsize=(10, 5))
# Build and draw the hierarchy tree
sch.dendrogram(sch.linkage(X, method="ward"))
plt.title("Dendrogram (Ward linkage)")
plt.xlabel("Data points")
plt.ylabel("Euclidean distance")
plt.show()

# ---------- Step 7: Agglomerative clustering ----------
# Bottom-up clustering into 4 groups
# Note: older scikit-learn used `affinity=`; newer versions need `metric=`
hc = AgglomerativeClustering(n_clusters=4, metric="euclidean", linkage="ward")
y_hc = hc.fit_predict(X)

# Plot hierarchical clusters
plt.scatter(X[:, 0], X[:, 1], c=y_hc, s=30, cmap="rainbow")
plt.title("Agglomerative Clustering")
plt.show()

# ---------- Step 8: Compare linkage methods ----------
methods = ["single", "complete", "average", "ward"]
plt.figure(figsize=(14, 8))
# One subplot per linkage method
for i, m in enumerate(methods, 1):
    plt.subplot(2, 2, i)
    sch.dendrogram(sch.linkage(X, method=m))
    plt.title(f"{m.capitalize()} linkage")
plt.tight_layout()
plt.show()
