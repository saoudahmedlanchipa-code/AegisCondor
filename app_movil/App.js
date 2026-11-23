// Aegis Condor - App móvil
// Se conecta al programa de la Raspberry Pi (puerto 5000) para ver el estado del sensor PIR,
// el video en vivo, recibir alertas y revisar el historial de capturas.
import { useEffect, useState } from 'react';
import { ActivityIndicator, Platform, StatusBar as RNStatusBar, StyleSheet, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import AsyncStorage from '@react-native-async-storage/async-storage';
import PantallaConexion from './src/PantallaConexion';
import PantallaPrincipal from './src/PantallaPrincipal';
import { colores } from './src/tema';

const CLAVE_IP = 'aegis_ip';

export default function App() {
  const [cargando, setCargando] = useState(true);
  const [ip, setIp] = useState('');
  const [conectado, setConectado] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(CLAVE_IP)
      .then((guardada) => {
        if (guardada) {
          setIp(guardada);
          setConectado(true);
        }
      })
      .finally(() => setCargando(false));
  }, []);

  async function conectar(nuevaIP) {
    await AsyncStorage.setItem(CLAVE_IP, nuevaIP);
    setIp(nuevaIP);
    setConectado(true);
  }

  return (
    <View style={estilos.raiz}>
      <StatusBar style="light" />
      {cargando ? (
        <ActivityIndicator style={{ flex: 1 }} color={colores.suave} />
      ) : conectado ? (
        <PantallaPrincipal ip={ip} onCambiarIP={() => setConectado(false)} />
      ) : (
        <PantallaConexion ipInicial={ip} onConectar={conectar} />
      )}
    </View>
  );
}

const estilos = StyleSheet.create({
  raiz: {
    flex: 1,
    backgroundColor: colores.fondo,
    paddingTop: Platform.OS === 'android' ? RNStatusBar.currentHeight ?? 24 : 54,
  },
});
