// Pantalla principal: estado del sensor, video en vivo, alertas e historial de capturas.
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert, Animated, Image, Modal, Pressable, RefreshControl, ScrollView, StyleSheet, Text,
  Vibration, View,
} from 'react-native';
import { setAudioModeAsync, useAudioPlayer } from 'expo-audio';
import {
  borrarEvento, cambiarArmado, obtenerEstado, obtenerEventos, urlBase,
} from './api';
import Logo from './Logo';
import { colores } from './tema';
import VideoEnVivo from './VideoEnVivo';

const PATRON_VIBRACION = [0, 400, 200, 400, 200, 400];

export default function PantallaPrincipal({ ip, onCambiarIP }) {
  const [estado, setEstado] = useState(null);
  const [conectado, setConectado] = useState(false);
  const [eventos, setEventos] = useState([]);
  const [refrescando, setRefrescando] = useState(false);
  const [fotoAbierta, setFotoAbierta] = useState(null);
  const [recargaVideo, setRecargaVideo] = useState(0);
  const ultimoIdRef = useRef(null);
  const fallosRef = useRef(0);
  const banner = useRef(new Animated.Value(-160)).current;

  const sirena = useAudioPlayer({ uri: `${urlBase(ip)}/alarma.wav` });

  useEffect(() => {
    setAudioModeAsync({ playsInSilentMode: true }).catch(() => {});
  }, []);

  const cargarEventos = useCallback(async () => {
    try {
      setEventos(await obtenerEventos(ip));
    } catch {}
  }, [ip]);

  // --- Módulo de alerta en el celular ---
  const alertar = useCallback(() => {
    Vibration.vibrate(PATRON_VIBRACION);
    try {
      sirena.seekTo(0);
      sirena.play();
    } catch {}
    Animated.sequence([
      Animated.spring(banner, { toValue: 0, useNativeDriver: true }),
      Animated.delay(4000),
      Animated.timing(banner, { toValue: -160, duration: 300, useNativeDriver: true }),
    ]).start();
  }, [sirena, banner]);

  // --- Consulta del estado cada 1 segundo ---
  useEffect(() => {
    let activo = true;
    async function consultar() {
      try {
        const e = await obtenerEstado(ip);
        if (!activo) return;
        if (!conectado && fallosRef.current > 0) setRecargaVideo((n) => n + 1);
        fallosRef.current = 0;
        setConectado(true);
        if (ultimoIdRef.current !== null && e.ultimo_evento_id > ultimoIdRef.current) {
          alertar();
          cargarEventos();
        }
        ultimoIdRef.current = e.ultimo_evento_id;
        setEstado(e);
      } catch {
        if (!activo) return;
        fallosRef.current += 1;
        if (fallosRef.current >= 2) setConectado(false);
      }
    }
    consultar();
    cargarEventos();
    const t1 = setInterval(consultar, 1000);
    const t2 = setInterval(cargarEventos, 15000);
    return () => {
      activo = false;
      clearInterval(t1);
      clearInterval(t2);
    };
  }, [ip, alertar, cargarEventos, conectado]);

  async function alternarArmado() {
    if (!estado) return;
    try {
      setEstado(await cambiarArmado(ip, !estado.armado));
    } catch {
      Alert.alert('Sin conexión', 'No se pudo cambiar el estado del sistema.');
    }
  }

  function confirmarBorrado(ev) {
    Alert.alert('Eliminar captura', `¿Eliminar la foto de las ${ev.hora}?`, [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Eliminar',
        style: 'destructive',
        onPress: async () => {
          try {
            await borrarEvento(ip, ev.archivo);
            setFotoAbierta(null);
            cargarEventos();
          } catch {
            Alert.alert('Error', 'No se pudo eliminar la captura.');
          }
        },
      },
    ]);
  }

  async function refrescar() {
    setRefrescando(true);
    setRecargaVideo((n) => n + 1);
    await cargarEventos();
    setRefrescando(false);
  }

  const tarjeta = describirEstado(estado, conectado);

  return (
    <View style={estilos.fondo}>
      <ScrollView
        contentContainerStyle={estilos.contenido}
        refreshControl={
          <RefreshControl refreshing={refrescando} onRefresh={refrescar} tintColor={colores.suave} />
        }
      >
        {/* Encabezado */}
        <View style={estilos.encabezado}>
          <View style={estilos.marca}>
            <Logo tamano={34} />
            <View>
              <Text style={estilos.titulo}>Aegis Condor</Text>
              <Text style={estilos.subtitulo}>{ip}</Text>
            </View>
          </View>
          <Pressable onPress={onCambiarIP} style={estilos.conexion} hitSlop={10}>
            <View style={[estilos.puntoConexion, { backgroundColor: conectado ? colores.ok : colores.gris }]} />
            <Text style={estilos.conexionTexto}>{conectado ? 'Conectado' : 'Sin conexión'}</Text>
            <Text style={estilos.engranaje}>⚙</Text>
          </Pressable>
        </View>

        {/* Estado */}
        <View style={[estilos.estado, tarjeta.alerta && estilos.estadoAlerta]}>
          <View style={[estilos.punto, { backgroundColor: tarjeta.color }]} />
          <View style={{ flex: 1 }}>
            <Text style={estilos.estadoTitulo}>{tarjeta.titulo}</Text>
            <Text style={estilos.estadoDetalle}>{tarjeta.detalle}</Text>
          </View>
        </View>

        {/* Video */}
        <VideoEnVivo ip={ip} recarga={recargaVideo} />

        {/* Datos */}
        <View style={estilos.fila}>
          <View style={estilos.dato}>
            <Text style={estilos.datoValor}>{estado ? estado.total_alertas : '–'}</Text>
            <Text style={estilos.datoEtiqueta}>Alertas en la sesión</Text>
          </View>
          <View style={estilos.dato}>
            <Text style={estilos.datoValor}>{estado ? estado.total_capturas : '–'}</Text>
            <Text style={estilos.datoEtiqueta}>Capturas guardadas</Text>
          </View>
        </View>

        {/* Armar / desarmar */}
        <Pressable
          onPress={alternarArmado}
          disabled={!estado}
          style={({ pressed }) => [
            estilos.boton,
            { backgroundColor: estado?.armado ? colores.botonGris : colores.acento },
            pressed && { opacity: 0.85 },
          ]}
        >
          <Text style={estilos.botonTexto}>
            {!estado ? '–' : estado.armado ? '🔓  Desarmar sistema' : '🔒  Armar sistema'}
          </Text>
        </Pressable>

        {/* Historial */}
        <View style={estilos.tarjeta}>
          <Text style={estilos.tarjetaTitulo}>Historial de detecciones</Text>
          {eventos.length === 0 ? (
            <Text style={estilos.vacio}>Aún no hay detecciones.</Text>
          ) : (
            eventos.map((ev) => (
              <Pressable key={ev.archivo} style={estilos.item} onPress={() => setFotoAbierta(ev)}>
                <Image source={{ uri: urlBase(ip) + ev.url }} style={estilos.miniatura} />
                <View>
                  <Text style={estilos.itemHora}>{ev.hora}</Text>
                  <Text style={estilos.itemFecha}>{ev.fecha}</Text>
                </View>
              </Pressable>
            ))
          )}
        </View>
      </ScrollView>

      {/* Aviso emergente */}
      <Animated.View style={[estilos.banner, { transform: [{ translateY: banner }] }]}>
        <Text style={estilos.bannerTexto}>⚠️  ¡Movimiento detectado en la zona!</Text>
      </Animated.View>

      {/* Foto ampliada */}
      <Modal visible={!!fotoAbierta} transparent animationType="fade" onRequestClose={() => setFotoAbierta(null)}>
        <View style={estilos.modal}>
          {fotoAbierta && (
            <>
              <Image
                source={{ uri: urlBase(ip) + fotoAbierta.url }}
                style={estilos.fotoGrande}
                resizeMode="contain"
              />
              <Text style={estilos.modalTexto}>{fotoAbierta.fecha} · {fotoAbierta.hora}</Text>
              <View style={estilos.modalAcciones}>
                <Pressable style={[estilos.modalBoton, { backgroundColor: '#7f1d1d' }]} onPress={() => confirmarBorrado(fotoAbierta)}>
                  <Text style={estilos.botonTexto}>Eliminar</Text>
                </Pressable>
                <Pressable style={[estilos.modalBoton, { backgroundColor: colores.botonGris }]} onPress={() => setFotoAbierta(null)}>
                  <Text style={estilos.botonTexto}>Cerrar</Text>
                </Pressable>
              </View>
            </>
          )}
        </View>
      </Modal>
    </View>
  );
}

function describirEstado(e, conectado) {
  if (!conectado || !e)
    return { titulo: 'Sin conexión', detalle: 'Revisa que la Raspberry esté encendida', color: colores.gris };
  if (!e.listo)
    return { titulo: 'Calibrando sensor', detalle: 'Espera unos segundos…', color: colores.aviso };
  if (!e.armado)
    return { titulo: 'Sistema desarmado', detalle: 'No se registran alertas', color: colores.gris };
  const modo = e.valla
    ? `${e.valla.nombre_modo}${e.valla.definida ? '' : ' (sin valla dibujada)'}`
    : '';
  if (e.alerta)
    return {
      titulo: '¡ALERTA! Persona en zona',
      detalle: `Desde las ${e.inicio_alerta}${e.silenciado ? ' · sirena silenciada' : ''}\nModo: ${modo}`,
      color: colores.alerta,
      alerta: true,
    };
  if (e.en_valla)
    return { titulo: 'Movimiento en la valla', detalle: `Verificando con el sensor PIR…\nModo: ${modo}`, color: colores.aviso };
  return { titulo: 'Zona despejada', detalle: `Vigilando · ${e.hora}\nModo: ${modo}`, color: colores.ok };
}

const estilos = StyleSheet.create({
  fondo: { flex: 1, backgroundColor: colores.fondo },
  contenido: { padding: 16, paddingBottom: 40 },
  encabezado: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 },
  marca: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  titulo: { color: colores.texto, fontSize: 19, fontWeight: '700' },
  subtitulo: { color: colores.suave, fontSize: 12 },
  conexion: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  puntoConexion: { width: 8, height: 8, borderRadius: 4 },
  conexionTexto: { color: colores.suave, fontSize: 12 },
  engranaje: { color: colores.suave, fontSize: 18, marginLeft: 4 },

  estado: {
    flexDirection: 'row', alignItems: 'center', gap: 14, padding: 18, borderRadius: 16,
    backgroundColor: colores.tarjeta, borderWidth: 1, borderColor: colores.borde, marginBottom: 14,
  },
  estadoAlerta: { backgroundColor: colores.alertaFondo, borderColor: colores.alerta },
  punto: { width: 44, height: 44, borderRadius: 22 },
  estadoTitulo: { color: colores.texto, fontSize: 18, fontWeight: '700' },
  estadoDetalle: { color: colores.suave, fontSize: 13, marginTop: 2 },

  fila: { flexDirection: 'row', gap: 10, marginBottom: 14 },
  dato: {
    flex: 1, backgroundColor: colores.tarjeta, borderWidth: 1, borderColor: colores.borde,
    borderRadius: 14, padding: 14,
  },
  datoValor: { color: colores.texto, fontSize: 24, fontWeight: '700' },
  datoEtiqueta: { color: colores.suave, fontSize: 12, marginTop: 2 },

  boton: { borderRadius: 14, paddingVertical: 16, alignItems: 'center', marginBottom: 14 },
  botonTexto: { color: '#fff', fontSize: 16, fontWeight: '700' },

  tarjeta: {
    backgroundColor: colores.tarjeta, borderWidth: 1, borderColor: colores.borde,
    borderRadius: 16, overflow: 'hidden',
  },
  tarjetaTitulo: { color: colores.suave, fontSize: 14, fontWeight: '600', padding: 14 },
  vacio: { color: colores.suave, padding: 14, borderTopWidth: 1, borderTopColor: colores.borde },
  item: {
    flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 10,
    borderTopWidth: 1, borderTopColor: colores.borde,
  },
  miniatura: { width: 76, height: 57, borderRadius: 8, backgroundColor: '#000' },
  itemHora: { color: colores.texto, fontSize: 15, fontWeight: '600' },
  itemFecha: { color: colores.suave, fontSize: 12 },

  banner: {
    position: 'absolute', left: 16, right: 16, top: 12, backgroundColor: colores.alerta,
    borderRadius: 14, padding: 16, elevation: 8,
    shadowColor: '#000', shadowOpacity: 0.4, shadowRadius: 12, shadowOffset: { width: 0, height: 6 },
  },
  bannerTexto: { color: '#fff', fontSize: 16, fontWeight: '700' },

  modal: { flex: 1, backgroundColor: 'rgba(0,0,0,0.93)', justifyContent: 'center', alignItems: 'center', padding: 16 },
  fotoGrande: { width: '100%', aspectRatio: 4 / 3, borderRadius: 10 },
  modalTexto: { color: colores.suave, marginVertical: 14 },
  modalAcciones: { flexDirection: 'row', gap: 10, width: '100%' },
  modalBoton: { flex: 1, borderRadius: 12, paddingVertical: 14, alignItems: 'center' },
});
