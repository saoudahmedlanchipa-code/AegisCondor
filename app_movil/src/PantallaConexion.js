// Pantalla de conexión: el usuario escribe la IP que muestra la Raspberry al iniciar.
import { useState } from 'react';
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { limpiarIP, probarConexion, PUERTO } from './api';
import Logo from './Logo';
import { colores } from './tema';

export default function PantallaConexion({ ipInicial = '', onConectar }) {
  const [ip, setIp] = useState(ipInicial);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState('');

  async function conectar() {
    const limpia = limpiarIP(ip);
    if (!limpia) {
      setError('Escribe la IP de la Raspberry Pi.');
      return;
    }
    setCargando(true);
    setError('');
    try {
      const r = await probarConexion(limpia);
      if (r.sistema !== 'Aegis Condor') throw new Error('respuesta inesperada');
      onConectar(limpia);
    } catch {
      setError(
        `No se pudo conectar a ${limpia}:${PUERTO}.\n` +
          'Revisa que el programa esté abierto en la Raspberry y que el celular esté en la misma red Wi-Fi.'
      );
    } finally {
      setCargando(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={estilos.fondo}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={estilos.centro}>
        <Logo tamano={72} />
        <Text style={estilos.titulo}>Aegis Condor</Text>
        <Text style={estilos.sub}>Seguridad en alturas</Text>

        <Text style={estilos.etiqueta}>IP de la Raspberry Pi</Text>
        <TextInput
          style={estilos.input}
          value={ip}
          onChangeText={setIp}
          placeholder="Ej: 192.168.1.50"
          placeholderTextColor={colores.gris}
          keyboardType={Platform.OS === 'ios' ? 'numbers-and-punctuation' : 'default'}
          autoCapitalize="none"
          autoCorrect={false}
          onSubmitEditing={conectar}
          returnKeyType="go"
        />
        <Text style={estilos.ayuda}>
          La IP aparece en la terminal de la Raspberry al abrir el programa.
        </Text>

        {error ? <Text style={estilos.error}>{error}</Text> : null}

        <Pressable
          style={({ pressed }) => [estilos.boton, pressed && { opacity: 0.85 }]}
          onPress={conectar}
          disabled={cargando}
        >
          {cargando ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={estilos.botonTexto}>Conectar</Text>
          )}
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const estilos = StyleSheet.create({
  fondo: { flex: 1, backgroundColor: colores.fondo },
  centro: { flex: 1, justifyContent: 'center', padding: 28, alignItems: 'stretch' },
  titulo: { color: colores.texto, fontSize: 28, fontWeight: '700', textAlign: 'center', marginTop: 14 },
  sub: { color: colores.suave, fontSize: 15, textAlign: 'center', marginBottom: 40 },
  etiqueta: { color: colores.suave, fontSize: 14, marginBottom: 8 },
  input: {
    backgroundColor: colores.tarjeta,
    borderColor: colores.borde,
    borderWidth: 1,
    borderRadius: 14,
    color: colores.texto,
    fontSize: 18,
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  ayuda: { color: colores.gris, fontSize: 13, marginTop: 8 },
  error: {
    color: '#fca5a5',
    backgroundColor: colores.alertaFondo,
    borderRadius: 12,
    padding: 12,
    marginTop: 16,
    fontSize: 14,
    lineHeight: 20,
  },
  boton: {
    backgroundColor: colores.acento,
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 24,
  },
  botonTexto: { color: '#fff', fontSize: 17, fontWeight: '700' },
});
