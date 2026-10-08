let session = crypto.randomUUID();
const $ = id => document.getElementById(id);
$('reset').onclick = () => {session = crypto.randomUUID(); $('messages').replaceChildren(); $('error').textContent = '';};
$('chat').onsubmit = async event => {
  event.preventDefault();
  const message = $('message').value;
  const add = (text, kind) => {const p = document.createElement('p'); p.className = kind; p.textContent = text; $('messages').append(p); p.scrollIntoView({block:'nearest'});};
  add(message, 'user'); $('message').value = '';
  try {
    const response = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message, user:$('user').value, mode:$('mode').value, session_id:session})});
    const data = await response.json(); if (!response.ok) throw Error(data.detail || 'Request failed.');
    add(data.response, 'assistant'); $('error').textContent = '';
  } catch (error) {$('error').textContent = error.message;}
};
