import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer, WordNetLemmatizer


text = "I am learning Natural Language Processing and running experiments efficiently."
tokens = word_tokenize(text)
filtered = [w for w in tokens if w.lower() not in set(stopwords.words("english"))]
stems = [PorterStemmer().stem(w) for w in filtered]
lemmas = [WordNetLemmatizer().lemmatize(w.lower(), pos="v") for w in filtered]

print("ORIGINAL TEXT:")
print(text)

print("\n1. TOKENS:")
print(tokens)

print("\n2. FILTERED TOKENS (STOPWORDS REMOVED):")
print(filtered)

print("\n3. STEMMED WORDS:")
print(stems)

print("\n4. LEMMATIZED WORDS:")
print(lemmas)
