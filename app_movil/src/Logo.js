// Logo dibujado con vistas (sin imágenes ni librerías extra)
import { StyleSheet, Text, View } from 'react-native';
import { colores } from './tema';

export default function Logo({ tamano = 36 }) {
  return (
    <View
      style={[
        estilos.escudo,
        { width: tamano, height: tamano * 1.1, borderRadius: tamano * 0.28,
          borderBottomLeftRadius: tamano * 0.5, borderBottomRightRadius: tamano * 0.5 },
      ]}
    >
      <Text style={{ fontSize: tamano * 0.5, color: '#fff' }}>⛰</Text>
    </View>
  );
}

const estilos = StyleSheet.create({
  escudo: {
    backgroundColor: colores.acento,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
  },
});
