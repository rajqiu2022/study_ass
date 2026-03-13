import https from 'https';
import WebSocket from 'ws';

const appId = '1903238384';
const secret = 'K5qcPC0odSI90skdWQKFB741zxwvvwxz';

async function getToken() {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify({ appId, clientSecret: secret });
    const req = https.request('https://bots.qq.com/app/getAppAccessToken', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': data.length }
    }, res => {
      let body = '';
      res.on('data', d => body += d);
      res.on('end', () => resolve(JSON.parse(body).access_token));
    });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

const token = await getToken();
console.log('Token obtained');

const gwRes = await fetch('https://api.sgroup.qq.com/gateway', {
  headers: { Authorization: `QQBot ${token}` }
});
const { url } = await gwRes.json();
console.log('Gateway URL:', url);

const ws = new WebSocket(url);
let lastSeq = null;
let hbTimer = null;

ws.on('open', () => console.log(new Date().toISOString(), 'WS OPEN'));
ws.on('close', (c, r) => {
  console.log(new Date().toISOString(), 'WS CLOSE code=' + c, 'reason=' + r?.toString());
  clearInterval(hbTimer);
});
ws.on('error', e => console.log(new Date().toISOString(), 'WS ERROR', e.message));
ws.on('pong', () => console.log(new Date().toISOString(), 'PONG received'));

ws.on('message', raw => {
  const msg = JSON.parse(raw);
  if (msg.s) lastSeq = msg.s;
  console.log(new Date().toISOString(), 'OP=' + msg.op, 't=' + msg.t, 's=' + msg.s);

  if (msg.op === 10) {
    // Hello - send immediate heartbeat first
    ws.send(JSON.stringify({ op: 1, d: lastSeq }));
    console.log(new Date().toISOString(), 'IMMEDIATE HB sent');
    // Then identify
    ws.send(JSON.stringify({
      op: 2,
      d: { token: 'QQBot ' + token, intents: 1107300352, shard: [0, 1] }
    }));
    console.log(new Date().toISOString(), 'IDENTIFY sent');
    // Start heartbeat timer
    const interval = msg.d.heartbeat_interval;
    console.log('HB interval:', interval, 'ms');
    hbTimer = setInterval(() => {
      if (ws.readyState === 1) {
        ws.send(JSON.stringify({ op: 1, d: lastSeq }));
        console.log(new Date().toISOString(), 'HB sent, seq=' + lastSeq);
      }
    }, interval);
    // Also ping every 15s
    setInterval(() => {
      if (ws.readyState === 1) {
        ws.ping();
        console.log(new Date().toISOString(), 'WS PING sent');
      }
    }, 15000);
  } else if (msg.op === 11) {
    console.log(new Date().toISOString(), 'HB ACK received');
  }
});

setTimeout(() => {
  console.log('TEST COMPLETE - connection survived 120s!');
  ws.close();
  process.exit(0);
}, 120000);
