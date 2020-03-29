from urllib import parse
from sanic import Sanic
from sanic.response import json
from requests import request
from numpy import argmax
from nltk import sent_tokenize

from core.api.api_wrapper import ClaimSpotterAPI

app = Sanic()
api = ClaimSpotterAPI()

def get_user_input(r, input_text, k="input_text"):
    try:
        if r.method == "GET":
            return parse.unquote_plus(input_text.strip())
        elif r.method == "POST":
            return r.json.get(k, "")
    except Exception as e:
        print(e)

    return ""

def get_url_score(url, tokenize_sentence=False):
    """
    Returns the scores of each sentence at the provided URL.

    Parameters
    ----------
    url : string
        Path to web page to score.
    tokenize_sentence : boolean
        Return a list of scored sentences instead of a single line.
    
    Returns
    -------
    list[dict]
        A list of dictionaries containing values for each `claim`, 
        it's `result`, and the `scores` associated with it.

        `claim` : string
        `result` : string
        `scores` : list[float]
    """
    
    url_text = requests.request('GET', url).text
    url_text = url_text.replace("\r", "")

    if tokenize_sentence:
        sentences = sent_tokenize(url_text)
    else:
        sentences = [url_text]
    
    results = []

    print(api.batch_sentence_query(sentences))

    for sentence in sentences:
        scores = api.single_sentence_query(results) if sentence else []
        idx = argmax(scores)

        results.append({'claim':sentence, 'result':api.return_strings[idx], 'scores':scores})

    return results

@app.route("/score/text/<input_text:(?!custom/).*>", methods=["POST", "GET"])
async def score_text(request, input_text):
    """
    Returns the scores of the text provided.

    Parameters
    ----------
    input_text : string
        Input text to be scored.
    
    Returns
    -------
    <Response>
        Returns a response object with the body containing a json-encoded dictionary containing the `claim`, it's `result`, and the `scores` associated with it.

        `claim` : string
        `result` : string
        `scores` : list[float]
    """
    input_text = get_user_input(request, input_text)
    sentences = sent_tokenize(input_text)
    scores = api.batch_sentence_query(sentences)

    print(sentences, scores)

    idx = argmax(scores)

    return json({'claim':input_text, 'result':api.return_strings[idx], 'scores':scores[1]})

@app.route("/score/url/<url:path>", methods=["POST", "GET"])
async def score_url(request, url):
    """
    Returns the scores of the text from the URL provided.

    Parameters
    ----------
    url : string
        Web page to be scored.
    
    Returns
    -------
    <Response>
        Returns a response object with the body containing a json-encoded list of dictionaries containing the `claim`, it's `result`, 
        and the `scores` associated with each claim on the web page.

        `claim` : string
        `result` : string
        `scores` : list[float]
    """
    url = get_user_input(request, url, "url")
    results = get_url_score(url, True)

    return json(results)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)