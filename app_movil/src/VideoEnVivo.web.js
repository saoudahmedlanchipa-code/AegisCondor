// Versión navegador del video en vivo: el navegador sí reproduce MJPEG en una imagen.
import { Image, StyleSheet, Text, View } from 'react-native';
import { urlBase } from './api';
import { colores } from './tema';

export default function VideoEnVivo({ ip, recarga }) {
  return (
    <View style={estilos.caja}>
      <Image
        key={`${ip}-${recarga}`}
        source={{ uri: `${urlBase(ip)}/video?r=${recarga}` }}
        style={estilos.video}
        resizeMode="contain"
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
    aspectRatio: 4 / 3, borderRadius: 16, overflow: 'hidden', backgroundColor: '#000',
    borderWidth: 1, borderColor: colores.borde, marginBottom: 14,
  },
  video: { width: '100%', height: '100%' },
  vivoCaja: { position: 'absolute', top: 10, left: 0, right: 0, alignItems: 'center' },
  vivo: {
    backgroundColor: 'rgba(239,68,68,0.9)',
    borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3,
  },
  vivoTexto: { color: '#fff', fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
});
