from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from gensim.models import Word2Vec

docs = ["I love artificial intelligence",
        "Deep learning is amazing",
        "Artificial intelligence is amazing"]

bow = CountVectorizer(stop_words="english")
print(bow.fit_transform(docs).toarray())          # word counts

tfidf = TfidfVectorizer(stop_words="english")
print(tfidf.fit_transform(docs).toarray().round(2))   # weighted scores

sentences = [["i","love","machine","learning"],
             ["machine","learning","is","amazing"],
             ["artificial","intelligence","is","amazing"]]
w2v = Word2Vec(sentences, vector_size=50, window=3, min_count=1)
print(len(w2v.wv["learning"]))                     # 50
