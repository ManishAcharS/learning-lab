# ---------- Step 1: Imports ----------
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.datasets import load_digits
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE

np.random.seed(42)  # Reproducibility

# ---------- Step 2: Load data ----------
digits = load_digits()
X = digits.data      # Features (pixel values)
y = digits.target    # Labels 0-9
print(X.shape, y.shape)  # (1797, 64) (1797,)

# Show the first image
# Note: sklearn digits = 64 features (8x8); full MNIST = 784
plt.imshow(digits.images[0], cmap="gray")
plt.title(f"Sample digit: {y[0]}")
plt.show()

# ---------- Step 3: Standardize ----------
# Zero mean, unit variance per feature
X_scaled = StandardScaler().fit_transform(X)
print(X_scaled.shape)  # (1797, 64)

# ---------- Step 4: PCA to 2D ----------
# Linear projection onto top 2 components
pca = PCA(n_components=2)
X_pca = pca.fit_transform(X_scaled)
print("Explained variance ratio:", pca.explained_variance_ratio_)
print("Total variance explained:", pca.explained_variance_ratio_.sum())

# ---------- Step 5: Visualize PCA ----------
plt.figure(figsize=(10, 7))
# Color points by digit label
sc = plt.scatter(X_pca[:, 0], X_pca[:, 1], c=y, cmap="tab10", alpha=0.7)
plt.legend(*sc.legend_elements(), title="Digits")
plt.xlabel("PC 1"); plt.ylabel("PC 2")
plt.title("PCA visualization")  # Result: classes mixed and overlapping
plt.show()

# ---------- Step 6: t-SNE to 2D ----------
# Non-linear embedding that preserves local neighborhoods
tsne = TSNE(n_components=2, random_state=42, perplexity=30)
X_tsne = tsne.fit_transform(X_scaled)
print(X_tsne.shape)

# ---------- Step 7: Visualize t-SNE ----------
plt.figure(figsize=(10, 7))
sc = plt.scatter(X_tsne[:, 0], X_tsne[:, 1], c=y, cmap="tab10", alpha=0.7)
plt.legend(*sc.legend_elements(), title="Digits")
plt.title("t-SNE visualization")  # Clusters should be clearly separated
plt.show()
