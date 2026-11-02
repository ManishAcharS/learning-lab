# Cell 1: Import required libraries
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from scipy.cluster.hierarchy import dendrogram, linkage
from sklearn.metrics import silhouette_score


# Cell 2: Download MovieLens dataset
import kagglehub
path = kagglehub.dataset_download("grouplens/movielens-latest-small")

print("Path to dataset files:", path)


# Cell 3: Load ratings dataset
import os
ratings = pd.read_csv(os.path.join(path, 'ratings.csv'))
ratings.head()


# Cell 4: Display dataset files
print(os.listdir(path))


# Cell 5: Create User x Movie matrix
user_movie = ratings.pivot_table(index='userId', columns='movieId', values='rating').fillna(0)
user_movie.shape


# Cell 6: Apply K-Means and Elbow Method
X = user_movie.values

inertia = []
for k in range(1, 8):
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    km.fit(X)
    inertia.append(km.inertia_)

plt.plot(range(1, 8), inertia, marker='o')
plt.xlabel('Number of Clusters')
plt.ylabel('Inertia')
plt.show()


# Cell 7: Calculate Silhouette Scores
for k in range(2, 6):
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = km.fit_predict(X)
    score = silhouette_score(X, labels)
    print(f'Silhouette Score for k={k}: {score}')


# Cell 8: PCA Visualization
pca = PCA(n_components=2)
X_pca = pca.fit_transform(X)

plt.scatter(X_pca[:, 0], X_pca[:, 1], alpha=0.5, c='blue')
plt.title('PCA Visualization')
plt.xlabel('PCA1')
plt.ylabel('PCA2')
plt.show()


# Cell 9: Hierarchical Clustering
linked = linkage(X[:100], 'ward')

plt.figure(figsize=(10, 5))
dendrogram(linked, orientation='top', distance_sort='descending')
plt.title('Hierarchical Clustering (Dendrogram) for 100 users')
plt.show()


# Cell 10: Download Fake News Dataset
import kagglehub

path = kagglehub.dataset_download("bhavikjikadara/fake-news-detection")

print("Path to dataset files:", path)


# Cell 11: Display Fake News Dataset Files
print(os.listdir(path))


# Cell 12: Load Fake and Real News Datasets
files = {f.lower(): f for f in os.listdir(path)}

fake = pd.read_csv(os.path.join(path, files['fake.csv']))
real = pd.read_csv(os.path.join(path, files['true.csv']))

fake['label'] = 'Fake'
real['label'] = 'Real'

ratings = pd.concat([fake, real], ignore_index=True)
ratings['text'] = ratings['text'].fillna('')

ratings.head()


# Cell 13: Train-Test Split and Vectorization
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import accuracy_score, classification_report

X = ratings['text']
y = ratings['label']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

cv = CountVectorizer(stop_words='english', max_features=5000)
X_train_cv = cv.fit_transform(X_train)
X_test_cv = cv.transform(X_test)


# Cell 14: Train Naive Bayes Model
from sklearn.metrics import confusion_matrix

model = MultinomialNB()
model.fit(X_train_cv, y_train)

y_pred = model.predict(X_test_cv)

print("Accuracy:", accuracy_score(y_test, y_pred))
print("\nClassification Report:\n", classification_report(y_test, y_pred))
print("\nConfusion Matrix:\n", confusion_matrix(y_test, y_pred))


# Cell 15: Test Model with Sample News
sample = ['Breaking: Scientists discover cure for cancer in new study.']
sample_cv = cv.transform(sample)

print('Prediction:', model.predict(sample_cv)[0])


# Cell 16: Install pgmpy

# Cell 17: Bayesian Network Example (Weather → Traffic)
from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.factors.discrete import TabularCPD
from pgmpy.inference import VariableElimination

bn_model = DiscreteBayesianNetwork([('Rain', 'Traffic')])

cpd_rain = TabularCPD('Rain', 2, [[0.7], [0.3]])  # 70% No Rain, 30% Rain

cpd_traffic = TabularCPD(
    'Traffic', 2,
    [[0.9, 0.4], [0.1, 0.6]],
    evidence=['Rain'],
    evidence_card=[2]
)

bn_model.add_cpds(cpd_rain, cpd_traffic)

inference = VariableElimination(bn_model)

print(inference.query(['Traffic'], evidence={'Rain': 1}))
