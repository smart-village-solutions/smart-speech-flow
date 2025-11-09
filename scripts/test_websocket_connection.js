// Simple WebSocket test using Node.js
const WebSocket = require('ws');

async function testWebSocket() {
    const wsUrl = 'ws://localhost:8000/ws/E8BF435B/admin';

    console.log(`Verbinde mit ${wsUrl}...`);

    const ws = new WebSocket(wsUrl);

    ws.on('open', function open() {
        console.log('✅ WebSocket-Verbindung erfolgreich!');

        // Sende Test-Nachricht
        const testMessage = {
            type: 'text_message',
            content: 'Hello WebSocket Test',
            timestamp: new Date().toISOString()
        };

        ws.send(JSON.stringify(testMessage));
        console.log('📤 Test-Nachricht gesendet');

        // Halte Verbindung 3 Sekunden offen
        setTimeout(() => {
            ws.close();
            console.log('🔌 WebSocket-Verbindung geschlossen');
        }, 3000);
    });

    ws.on('message', function message(data) {
        console.log(`📥 Antwort erhalten: ${data}`);
    });

    ws.on('error', function error(err) {
        console.error(`❌ WebSocket Fehler: ${err.message}`);
    });

    ws.on('close', function close() {
        console.log('🔌 Verbindung beendet');
        process.exit(0);
    });
}

testWebSocket();