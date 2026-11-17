"""Offline Vietnamese question classifier. Pure Python, JSON models, no network or pickle."""
from collections import Counter
import math
import re
import unicodedata

ALGORITHM = 'tfidf-v1'
STOP_WORDS = set('toi minh ban cho hoi xin hay giup voi cua la cac mot nhung duoc va thi ma'.split())


def normalize(text):
    text = unicodedata.normalize('NFKD', text.lower().replace('đ', 'd'))
    return ' '.join(re.findall(r'[a-z0-9]+', ''.join(c for c in text if not unicodedata.combining(c))))


def features(text):
    words = [word for word in normalize(text).split() if word not in STOP_WORDS]
    result = Counter('w:' + word for word in words)
    result.update('b:' + a + ' ' + b for a, b in zip(words, words[1:]))
    # Character features tolerate small typing errors; words remain dominant.
    for word in words:
        for i in range(len(word) - 2):
            result['c:' + word[i:i + 3]] += 0.15
    return result


def vector(text, idf, unknown):
    values = {term: (1 + math.log(count) if count >= 1 else count) * idf.get(term, unknown)
              for term, count in features(text).items()}
    length = math.sqrt(sum(value * value for value in values.values())) or 1
    return {term: value / length for term, value in values.items()}


def train(documents):
    samples, seen = [], {}
    for document in documents:
        for question in document['questions']:
            key = normalize(question)
            if key in seen:
                if seen[key] != document['id']:
                    raise ValueError('Câu hỏi trùng giữa các mục kiến thức: ' + question)
                continue
            if not features(question):
                raise ValueError('Câu hỏi cần có nội dung cụ thể: ' + question)
            seen[key] = document['id']
            samples.append(dict(document_id=document['id'], question=question, normalized=key))
    if not samples:
        raise ValueError('Cần ít nhất một mục kiến thức đang bật để huấn luyện.')
    counts = Counter()
    for sample in samples:
        counts.update(features(sample['question']).keys())
    idf = {term: math.log((len(samples) + 1) / (count + 1)) + 1 for term, count in counts.items()}
    unknown = math.log(len(samples) + 1) + 1
    for sample in samples:
        sample['vector'] = vector(sample['question'], idf, unknown)
    return dict(algorithm=ALGORITHM, documents=documents, samples=samples, idf=idf, unknown=unknown)


def predict(model, text, threshold):
    normalized = normalize(text)
    query = vector(text, model['idf'], model['unknown'])
    ranked = {}
    for sample in model['samples']:
        score = 1.0 if normalized == sample['normalized'] else sum(
            value * sample['vector'].get(term, 0) for term, value in query.items())
        key = sample['document_id']
        ranked[key] = max(ranked.get(key, 0), score)
    choices = sorted(ranked.items(), key=lambda item: (-item[1], item[0]))
    best_id, score = choices[0]
    # Similar scores across distinct topics require clarification rather than guessing.
    margin = score - choices[1][1] if len(choices) > 1 else score
    matched = score >= threshold and (score >= 0.999 or margin >= 0.07)
    document = next(item for item in model['documents'] if item['id'] == best_id)
    return dict(matched=matched, confidence=round(score, 4),
                title=document['title'] if matched else '', answer=document['answer'] if matched else '')
