const req1 = new XMLHttpRequest();
req1.onreadystatechange = function () {
    if (this.readyState === 4 && this.status === 200) {
        obj = JSON.parse(this.responseText);
        const nodes = document.querySelectorAll(".search-result-container");
        for (let i = 0; i < obj.results.length; i++) {
            nodes[i].innerText = obj.results[i].title;
            nodes[i].onclick = () => {
                req2.open("GET", `/jukebox/web/{chat_id}/add?track_id=${obj.results[i].track_id}`);
                req2.setRequestHeader("Accept", "application/json");
                req2.setRequestHeader("Content-Type", "application/json");
                req2.send();
            };
        }
    }
};

const req2 = new XMLHttpRequest();
req2.onreadystatechange = function () {
    if (this.readyState === 4 && this.status === 200) {
        obj = JSON.parse(this.responseText);
        window.location.href = obj.payment_url;
    }
};

function submitSearch() {
    req1.open("POST", "/jukebox/web/{chat_id}/search");
    req1.setRequestHeader("Accept", "application/json");
    req1.setRequestHeader("Content-Type", "application/json");
    req1.send(JSON.stringify({ query: document.getElementsByName("query")[0].value }));
}
