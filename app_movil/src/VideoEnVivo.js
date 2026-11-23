// Video en vivo (MJPEG) que entrega la Raspberry en /video.
// Se muestra dentro de un WebView porque el componente Image de React Native no reproduce MJPEG.
import { StyleSheet, Text, View } from 'react-native';
import { WebView } from 'react-native-webview';
import { urlBase } from './api';
import { colores } from './tema';

export default function VideoEnVivo({ ip, recarga }) {
  const base = urlBase(ip);
  const html = `<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
img{width:100%;height:100%;object-fit:contain}</style></head>
<body><img id="v" src="${base}/video">
<script>
  var v = document.getElementById('v');
  v.onerror = function () { setTimeout(function () { v.src = '${base}/video?t=' + Date.now(); }, 2000); };
</script></body></html>`;

  return (
    <View style={estilos.caja}>
      <WebView
        key={`${ip}-${recarga}`}
        source={{ html, baseUrl: base }}
        originWhitelist={['*']}
        mixedContentMode="always"
        scrollEnabled={false}
        style={estilos.web}
      />
      <View style={estilos.vivoCaja} pointerEvents="none">
        <View style={estilos.vivo}>
          <Text style={estilos.vivoTexto}>● EN VIVO</Text>
        </View>
      </View>
    </View>
  );
}

const estilos = StyleSheet.create({
  caja: {
    aspectRatio: 4 / 3,
    borderRadius: 16,
    overflow: 'hidden',
    backgroundColor: '#000',
    borderWidth: 1,
    borderColor: colores.borde,
    marginBottom: 14,
  },
  web: { flex: 1, backgroundColor: '#000' },
  vivoCaja: { position: 'absolute', top: 10, left: 0, right: 0, alignItems: 'center' },
  vivo: {
    backgroundColor: 'rgba(239,68,68,0.9)',
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  vivoTexto: { color: '#fff', fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
});
