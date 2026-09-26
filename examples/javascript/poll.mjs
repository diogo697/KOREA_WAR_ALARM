const headers = process.env.KWA_API_TOKEN ? {Authorization: `Bearer ${process.env.KWA_API_TOKEN}`} : {};
const response = await fetch('http://127.0.0.1:8080/api/v1/alert/simple', {headers});
if (!response.ok) throw new Error(`HTTP ${response.status}`);
console.log(await response.json());
