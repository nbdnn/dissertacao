import { useState, useEffect, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Html, Line } from '@react-three/drei';
import { Send, AlertTriangle, Activity, Settings2, ShieldAlert, CheckCircle2, Zap, Orbit, Database, Radio, Clock, Search, List } from 'lucide-react';
import * as THREE from 'three';
import * as satellite from 'satellite.js';
import './index.css';

// ==============================================
// Types & Interfaces
// ==============================================
interface VizierData {
  type: string;
  study_id: string;
  target: number;
  trials: { iter: number; dv: number; dt: number }[];
  optimal: { dv_ms: number; dt_s: number };
}

interface Message {
  role: 'user' | 'agent';
  text: string;
  vizierData?: VizierData | null;
}

// Mock alerts replaced with dynamic spatial TCA nodes

// Visual Constants
const EARTH_RADIUS_KM = 6371;

function EarthMesh({ gmst, earthRef }: { gmst: number, earthRef: any }) {
  // Rotate the earth dynamically underneath the ECI tracking coordinates
  return (
    <mesh ref={earthRef} rotation={[0, gmst, 0]}>
      <sphereGeometry args={[1, 64, 64]} />
      <meshStandardMaterial map={new THREE.TextureLoader().load('/earth-blue-marble.jpg')} />
    </mesh>
  );
}

function GroundTrackLine({ points, vertexColors, isDashed }: { points: THREE.Vector3[], vertexColors: THREE.Color[], isDashed: boolean }) {
  // Convert THREE.Color to [r,g,b] arrays for Drei's Line
  const colors = vertexColors ? vertexColors.map(c => [c.r, c.g, c.b]) : undefined;
  
  return (
    <Line 
       points={points}
       vertexColors={colors as any}
       color={colors ? "white" : "white"} // Fallback base color
       lineWidth={isDashed ? 1.5 : 2.5} 
       dashed={isDashed}
       dashSize={0.05}
       gapSize={0.05}
       transparent
       opacity={0.8}
    />
  );
}

function GlobeSatelliteMesh({ 
  isEvasive, 
  primaryTLE, 
  threatTLE,
  historyTles,
  onCheckpointsGenerated,
  timeOffset,
  earthRef
}: { 
  isEvasive: boolean;
  primaryTLE: any;
  threatTLE: any;
  historyTles: any[];
  onCheckpointsGenerated: (cps: any[]) => void;
  timeOffset: number;
  earthRef: any;
}) {
  const [orbitLines, setOrbitLines] = useState<any[]>([]);

  // Exact requested time in the universe
  const time = new Date(Date.now() + (timeOffset * 60000));
  const gmst = satellite.gstime(time);

  // Generate Paths directly in Native Cartesian Mode
  useEffect(() => {
    if (!primaryTLE?.satrec || !threatTLE?.satrec) return;

    const newPaths: any[] = [];
    const newCps: any[] = [];

    const generateLine = (satrec: any, name: string, isEvasiveTarget: boolean = false, isGhost: boolean = false) => {
        const pastPoints: THREE.Vector3[] = [];
        const futurePoints: THREE.Vector3[] = [];
        const pastColors: THREE.Color[] = [];
        const futureColors: THREE.Color[] = [];
        const baseTime = new Date(); // Lines are generated based on true NOW

        let globalMinDist = Infinity;
        let closestTcaNode: any = null;

        for(let i = -30; i <= 100; i++) {
           const t = new Date(baseTime.getTime() + i*60000);
           const pEci = satellite.propagate(satrec, t);
           if (pEci?.position && typeof pEci.position !== 'boolean') {
               const px = (pEci.position as any).x;
               const py = (pEci.position as any).y;
               const pz = (pEci.position as any).z;
               
               let scale = 1 / EARTH_RADIUS_KM;
               if (isEvasiveTarget && i > 30) scale += (0.04 / EARTH_RADIUS_KM);
               const vec = new THREE.Vector3(px * scale, pz * scale, -py * scale); 

               // Calculate threat distance precisely at this vertex to tint the line as a heatmap
               let minThresholdDist = Infinity;
               if (name === primaryTLE?.name && threatTLE?.satrec) {
                   const tEci = satellite.propagate(threatTLE.satrec, t);
                   if (tEci?.position && typeof tEci.position !== 'boolean') {
                       const tx = (tEci.position as any).x;
                       const ty = (tEci.position as any).y;
                       const tz = (tEci.position as any).z;
                       minThresholdDist = Math.sqrt(Math.pow(px-tx, 2) + Math.pow(py-ty, 2) + Math.pow(pz-tz, 2));
                   }
               }

               // Color Interpolation (Heatmap)
               // > 2000km = standard white (#f8fafc)
               // < 2000km = shift to critical red (#ef4444)
               let vertexColor = new THREE.Color('#ffffff');
               if (isGhost) {
                   vertexColor = new THREE.Color('#a855f7'); // 4D Matrix Purple
               } else if (isEvasiveTarget) {
                   vertexColor = new THREE.Color('#10b981'); // Safe evasive path green
               } else if (minThresholdDist < 2000) {
                   const ratio = Math.max(0, 1 - (minThresholdDist / 2000));
                   vertexColor.lerp(new THREE.Color('#ef4444'), ratio); // Shift white to red
               }

               if (i <= 0) {
                   pastPoints.push(vec);
                   // Fade past lines slightly by darkening
                   pastColors.push(vertexColor.clone().multiplyScalar(isGhost ? 0.2 : 0.4));
               }
               if (i >= 0) {
                   futurePoints.push(vec);
                   futureColors.push(vertexColor.clone().multiplyScalar(isGhost ? 0.3 : 1.0));
               }

               // Exact minimum TCA check
               if (i > 0 && minThresholdDist < globalMinDist) {
                   globalMinDist = minThresholdDist;
                   closestTcaNode = { timeOffset: i, name, pos: vec, distKm: minThresholdDist };
               }
           }
        }
        
        newPaths.push({ points: pastPoints, vertexColors: pastColors, isDashed: false });
        newPaths.push({ points: futurePoints, vertexColors: futureColors, isDashed: true });
        
        // Push the most dangerous hotspot dot (if it's not a regular node already pushed)
        if (closestTcaNode && closestTcaNode.distKm < 5000) {
            newCps.push(closestTcaNode);
        }
    };

    generateLine(primaryTLE.satrec, primaryTLE.name);
    // Render threat without heatmap checks
    generateLine(threatTLE.satrec, threatTLE.name);

    if (historyTles && historyTles.length > 0) {
       historyTles.forEach((hSatrec: any, idx: number) => {
           // We could draw them as plain ghost lines or not at all, to avoid clutter
           generateLine(hSatrec, `HISTORICAL-${idx}`, false, true);
       });
    }

    if (isEvasive) {
       generateLine(primaryTLE.satrec, primaryTLE.name, true);
    }

    setOrbitLines(newPaths);
    onCheckpointsGenerated(newCps);
  }, [primaryTLE, threatTLE, isEvasive, historyTles]);

  // Handle active satellite positional markers
  const activeSats = [
    { ...primaryTLE, isPrimary: true, color: '#818cf8' }, 
    { ...threatTLE, isThreat: true, color: '#f87171' }
  ];

  return (
    <group>
      <EarthMesh gmst={gmst} earthRef={earthRef} />
      
      {/* Draw strict physical orbital paths using vertex coloring */}
      {orbitLines.map((line, idx) => (
         <GroundTrackLine key={`path-${idx}`} points={line.points} vertexColors={line.vertexColors} isDashed={line.isDashed} />
      ))}
      
      {/* Draw Scrubbed/Forecasted True Cartesian position spheres */}
      {activeSats.map((sat, idx) => {
         if (!sat.satrec) return null;
         const eci = satellite.propagate(sat.satrec, time);
         if (!eci?.position || typeof eci.position === 'boolean') return null;
         
         const px = (eci.position as any).x / EARTH_RADIUS_KM;
         const py = (eci.position as any).y / EARTH_RADIUS_KM;
         const pz = (eci.position as any).z / EARTH_RADIUS_KM;
         const pos: [number, number, number] = [px, pz, -py];

         return (
            <mesh key={`sat-${idx}`} position={pos}>
               <sphereGeometry args={[0.015, 16, 16]} />
               <meshStandardMaterial color={sat.color} emissive={sat.color} emissiveIntensity={2} />
            </mesh>
         );
      })}
    </group>
  );
}

// Helper to retrieve native Cartesian from raw TLE (without Geodetic distortions)
function getEciCoords(satrec: any, timeOffset: number) {
  const time = new Date(Date.now() + (timeOffset * 60000));
  const eci = satellite.propagate(satrec, time);
  if (eci?.position && typeof eci.position !== 'boolean') {
     const px = (eci.position as any).x / EARTH_RADIUS_KM;
     const py = (eci.position as any).y / EARTH_RADIUS_KM;
     const pz = (eci.position as any).z / EARTH_RADIUS_KM;
     return [px, pz, -py];
  }
  return [0,0,0];
}

function SatelliteHUD({ tle, isPrimary, timeOffset, earthRef }: { tle: any, isPrimary: boolean, timeOffset: number, earthRef: any }) {
  const groupRef = useRef<THREE.Group>(null);
  const [occluded, setOccluded] = useState(false);
  
  // Also hook the HUD tracking to the TimeOffset scrubber natively
  useEffect(() => {
    if (tle?.satrec && groupRef.current) {
        const pos = getEciCoords(tle.satrec, timeOffset);
        groupRef.current.position.set(pos[0], pos[1], pos[2]);
    }
  }, [tle, timeOffset]);

  if (!tle?.satrec) return null;

  const inc = (tle.satrec.inclo * 180 / Math.PI).toFixed(2);
  const ecc = tle.satrec.ecco.toFixed(5);
  const revs = (tle.satrec.no * 1440 / (Math.PI * 2)).toFixed(2);
  const bstar = tle.satrec.bstar.toExponential(2);

  return (
    <group ref={groupRef}>
      <Html center sprite distanceFactor={1.5} zIndexRange={[100, 0]} occlude={[earthRef]} onOcclude={setOccluded}>
        {isPrimary ? (
          <div className={`bg-slate-900/90 backdrop-blur-md rounded-lg border border-indigo-500/50 shadow-[0_0_20px_rgba(99,102,241,0.3)] p-2 transform transition-all duration-300 ${occluded ? 'opacity-0 pointer-events-none' : 'opacity-100 pointer-events-auto'}`}>
            <div className="flex items-center gap-1.5 border-b border-slate-700/50 pb-1 mb-1">
              <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse"></div>
              <span className="text-[10px] font-bold text-indigo-300 uppercase tracking-widest">{tle.name}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[8px] font-mono text-slate-300 mt-1">
              <div className="text-slate-500">INCLINATION</div>
              <div className="text-right text-indigo-200">{inc}°</div>
              <div className="text-slate-500">ECCENTRICITY</div>
              <div className="text-right text-indigo-200">{ecc}</div>
              <div className="text-slate-500">MEAN MOTION</div>
              <div className="text-right text-indigo-200">{revs} <span className="text-[6px]">REV/D</span></div>
              <div className="text-slate-500">BSTAR DRAG</div>
              <div className="text-right text-indigo-200">{bstar}</div>
            </div>
          </div>
        ) : (
          <div className={`px-2 py-0.5 rounded text-[10px] whitespace-nowrap border flex items-center gap-1 transition-all duration-300 shadow-[0_0_10px_rgba(239,68,68,0.5)] ${occluded ? 'opacity-0 pointer-events-none scale-90' : 'opacity-90 bg-red-900/80 border-red-500 text-red-100 scale-100 pointer-events-auto'}`}>
            <ShieldAlert size={10} />
            {tle.name}
          </div>
        )}
      </Html>
    </group>
  );
}

function Checkpoint3D({ cp, onCommandAgent, earthRef }: { cp: any, onCommandAgent: (cmd: string) => void, earthRef: any }) {
  const [hovered, setHovered] = useState(false);
  const [occluded, setOccluded] = useState(false);
  const isPrimary = cp.name.includes("SPACEMOBILE");

  return (
    <group position={cp.pos}>
      <mesh 
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
        onPointerOut={() => setHovered(false)}
        onClick={(e) => { e.stopPropagation(); onCommandAgent(`Analyze trajectory and spawn Vizier study for ${cp.name} at T+${cp.timeOffset}m.`); }}
      >
        <sphereGeometry args={[0.02, 16, 16]} />
        <meshBasicMaterial color={isPrimary ? '#ef4444' : '#94a3b8'} />
      </mesh>
      
      <mesh>
        <sphereGeometry args={[hovered ? 0.03 : 0.025, 16, 16]} />
        <meshBasicMaterial color='#f87171' transparent opacity={hovered ? 0.4 : 0.15} />
      </mesh>

      {/* Permanently visible TCA Hotspot Label */}
      <Html center position={[0, 0.04, 0]} distanceFactor={1.5} zIndexRange={[100, 0]} style={{ pointerEvents: 'none' }} occlude={[earthRef]} onOcclude={setOccluded}>
         <div className={`bg-slate-900/90 backdrop-blur-md rounded-lg border border-slate-600 p-2 shadow-xl transition-all duration-300 ${occluded ? 'opacity-0 scale-90' : 'opacity-100 scale-100'}`}>
           <div className="text-[10px] font-bold text-slate-200 mb-1 flex items-center gap-1.5 border-b border-slate-700/50 pb-1">
             <ShieldAlert size={10} className="text-red-400" />
             {cp.name} TCA
           </div>
           <div className="text-[9px] text-slate-300 mb-2">
             <span className="text-slate-500">DISTANCE: </span> 
             {cp.distKm < 500 ? <span className="text-red-400 font-bold">{cp.distKm.toFixed(0)}km</span> : `${cp.distKm.toFixed(0)}km`} <br/>
             <span className="text-slate-500">TIME REMAINING: </span> T+{cp.timeOffset}m
           </div>
           {isPrimary && hovered && (
             <button 
               className="bg-indigo-600/50 hover:bg-indigo-500/80 text-white text-[8px] font-bold px-2 py-1 rounded transition-colors w-full border border-indigo-400/30 font-mono flex items-center justify-center gap-1 pointer-events-auto"
             >
               <Zap size={8} /> REQUEST VIZIER
             </button>
           )}
         </div>
      </Html>
    </group>
  );
}

function Center3DView({ 
  isEvasive, 
  onCommandAgent, 
  primaryTLE, 
  threatTLE, 
  historyTles, 
  timeOffset,
  checkpoints,
  setCheckpoints,
  focusTarget
}: any) {
  const controlsRef = useRef<any>(null);
  const earthRef = useRef<any>(null);

  return (
    <div className="w-full h-full relative bg-slate-950 rounded-xl overflow-hidden shadow-inset border border-slate-700/50">
      
      {/* Floating Evasion Badge on Bottom Center */}
      {isEvasive && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10 bg-emerald-900/80 backdrop-blur px-4 py-2 rounded-full text-emerald-300 font-bold border border-emerald-500 shadow-[0_0_20px_rgba(16,185,129,0.5)] flex items-center gap-2 animate-pulse">
          <ShieldAlert size={16} /> EVASIVE MANEUVER ACTIVE
        </div>
      )}

      <Canvas camera={{ position: [0, 0, 3], fov: 50 }}>
        <CameraController focusTarget={focusTarget} controlsRef={controlsRef} />
        <ambientLight intensity={0.5} />
        <pointLight position={[100, 100, 100]} intensity={1} />
        <directionalLight position={[-50, 50, -50]} intensity={0.5} />
        <OrbitControls ref={controlsRef} makeDefault enableDamping dampingFactor={0.05} enablePan={false} minDistance={1.2} maxDistance={5.0} />
        
        {/* Parent transform group holding both the globe and exactly-mapped Html nodes */}
        <group>
          
          {/* Realistic Globe & Satellites (Replacing simple Sphere) */}
          <GlobeSatelliteMesh 
            isEvasive={isEvasive} 
            primaryTLE={primaryTLE} 
            threatTLE={threatTLE} 
            historyTles={historyTles}
            onCheckpointsGenerated={setCheckpoints} 
            timeOffset={timeOffset}
            earthRef={earthRef}
          />

          {/* Dynamic HTML Labels tracked to their global positions via Dedicated Hook Components */}
          {primaryTLE && <SatelliteHUD tle={primaryTLE} isPrimary={true} timeOffset={timeOffset} earthRef={earthRef} />}
          {threatTLE && <SatelliteHUD tle={threatTLE} isPrimary={false} timeOffset={timeOffset} earthRef={earthRef} />}

          {/* Post-maneuver Evasive Trajectory Badge (anchored relative scale) */}
          {isEvasive && primaryTLE && (
             <Html position={[0, 130, 0]} center sprite occlude={[earthRef]}>
               <div className="bg-emerald-900/90 px-2 py-1 rounded text-[10px] whitespace-nowrap border border-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.8)] text-emerald-100 flex items-center gap-1">
                 <CheckCircle2 size={10} /> POST-MANEUVER SAFE ZONE
               </div>
             </Html>
          )}

          {/* Interactive Physical Checkpoints along the forecasted routes */}
          {checkpoints.map((cp, idx) => (
             <Checkpoint3D key={`cp-${idx}`} cp={cp} onCommandAgent={onCommandAgent} earthRef={earthRef} />
          ))}
        </group>

      </Canvas>
    </div>
  );
}

function IntelligenceSidebar({
  trackInput,
  setTrackInput,
  handleMarkSatellite,
  syncStatus,
  show4D,
  setShow4D,
  primaryName,
  timeOffset,
  setTimeOffset,
  checkpoints,
  setFocusTarget,
  focusTarget,
  onCommandAgent
}: any) {
  const [activeTab, setActiveTab] = useState<'matrix' | 'catalog'>('matrix');
  const [catalog, setCatalog] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loadingCatalog, setLoadingCatalog] = useState(false);

  useEffect(() => {
    if (activeTab === 'catalog' && catalog.length === 0) {
      setLoadingCatalog(true);
      fetch('http://localhost:8080/api/tles')
        .then(res => res.json())
        .then(data => {
            if (data.tles) setCatalog(data.tles);
        })
        .finally(() => setLoadingCatalog(false));
    }
  }, [activeTab]);

  const filteredCatalog = catalog.filter(sat => 
    (sat.OBJECT_NAME && sat.OBJECT_NAME.toLowerCase().includes(searchQuery.toLowerCase())) ||
    (sat.NORAD_CAT_ID && String(sat.NORAD_CAT_ID).includes(searchQuery))
  ).slice(0, 50);

  return (
    <div className="w-80 flex-shrink-0 bg-slate-800/60 border border-slate-700 rounded-xl flex flex-col overflow-hidden shadow-lg backdrop-blur-md">
       <div className="flex border-b border-slate-700 bg-slate-800/80 shrink-0">
          <button 
             onClick={() => setActiveTab('matrix')}
             className={`flex-1 py-3 text-xs font-bold uppercase tracking-wider flex justify-center items-center gap-2 transition-colors ${activeTab === 'matrix' ? 'text-indigo-400 border-b-2 border-indigo-500 bg-slate-800' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-700/50'}`}
          >
             <Activity size={14} /> Matrix
          </button>
          <button 
             onClick={() => setActiveTab('catalog')}
             className={`flex-1 py-3 text-xs font-bold uppercase tracking-wider flex justify-center items-center gap-2 transition-colors ${activeTab === 'catalog' ? 'text-indigo-400 border-b-2 border-indigo-500 bg-slate-800' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-700/50'}`}
          >
             <List size={14} /> Catalog
          </button>
       </div>
      
      {activeTab === 'matrix' ? (
        <div className="flex-1 flex flex-col overflow-y-auto">
          {/* Target Metric Header */}
      <div className="p-4 border-b border-slate-700 bg-slate-800 flex items-center justify-between">
         <div className="flex items-center gap-2">
            <div className="w-10 h-10 rounded-lg bg-indigo-900/50 border border-indigo-500/30 flex justify-center items-center text-indigo-400">
               <Orbit size={20} />
            </div>
            <div>
               <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Primary Target</div>
               <div className="font-semibold text-slate-100">{primaryName || "AWAITING SYNC"}</div>
            </div>
         </div>
      </div>

      {/* Matrix Controls */}
      <div className="p-4 flex flex-col gap-4 border-b border-slate-700/50">
        <div>
          <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-2">
            <Database size={12} className="text-slate-400" />
            Vertex AI Matrix
          </h3>
          <div className="flex gap-2 mb-3">
            <input 
              type="text" 
              value={trackInput}
              onChange={e => setTrackInput(e.target.value)}
              className="bg-slate-900/80 border border-slate-700 rounded-md px-3 py-1.5 text-xs text-slate-200 w-full focus:outline-none focus:border-indigo-500 focus:bg-slate-900 transition-colors"
              placeholder="NORAD ID"
            />
            <button 
              onClick={handleMarkSatellite}
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded-md text-xs font-bold whitespace-nowrap transition-colors shadow-sm"
            >
              Sync Target
            </button>
          </div>
          
          <div className="bg-slate-900/60 rounded-md p-3 text-xs flex flex-col gap-2.5 border border-slate-700/50">
             <div className="flex items-center justify-between">
               <span className="text-slate-400 flex items-center gap-1"><Radio size={10} /> Stream (Pub/Sub)</span>
               <span className="text-emerald-400 flex items-center gap-1 font-mono text-[10px]">
                 <div className="w-1 h-1 rounded-full bg-emerald-500 animate-pulse"></div> ACTIVE
               </span>
             </div>
             <div className="flex items-center justify-between">
               <span className="text-slate-400 flex items-center gap-1"><Settings2 size={10} /> Cloud Workers</span>
               <span className="text-blue-400 font-mono text-[10px]">300x STANDBY</span>
             </div>
             <div className="flex items-center justify-between pt-1 border-t border-slate-700/50 mt-1">
               <span className="text-slate-300 font-semibold">Matrix State</span>
               {syncStatus === 'syncing' ? (
                 <span className="text-amber-400 animate-pulse font-mono font-bold text-[10px]">CALCULATING...</span>
               ) : syncStatus === 'active' ? (
                 <span className="text-emerald-400 font-mono font-bold text-[10px]">SYNCED / REAL-TIME</span>
               ) : (
                 <span className="text-slate-500 font-mono font-bold text-[10px]">IDLE</span>
               )}
             </div>
          </div>

          {/* Temporal Time Travel Scrubber */}
          <div className="flex flex-col gap-2 border-t border-slate-700/50 pt-3 mt-1">
            <div className="flex items-center justify-between text-slate-400">
               <span className="text-[10px] flex items-center gap-1"><Clock size={10} /> TEMPORAL SCRUBBER</span>
               <span className="font-mono text-[10px] font-bold text-indigo-300">
                 {timeOffset > 0 ? `+${timeOffset} min` : timeOffset < 0 ? `${timeOffset} min` : 'NOW'}
               </span>
            </div>
            
            <div className="px-1 py-2">
              <input 
                 type="range" 
                 min="-120" 
                 max="120" 
                 value={timeOffset} 
                 onChange={(e) => setTimeOffset(Number(e.target.value))}
                 className="w-full h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />
              <div className="flex justify-between text-[8px] text-slate-500 mt-1 font-mono">
                 <span>-2 HR</span>
                 <span>LIVE</span>
                 <span>+2 HR</span>
              </div>
            </div>
          </div>
        </div>

        {/* 4D Toggle */}
        <button 
          onClick={() => setShow4D(!show4D)}
          className={`w-full py-2.5 rounded-lg text-xs font-bold flex items-center justify-center gap-2 transition-all duration-300 border ${
            show4D 
              ? 'bg-purple-900/50 text-purple-200 border-purple-500 hover:bg-purple-800/50 shadow-[0_0_15px_rgba(168,85,247,0.3)]' 
              : 'bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700 hover:text-slate-200'
          }`}
        >
          <Activity size={14} />
          {show4D ? 'DISABLE 4D MATRIX' : 'ACTIVATE 4D MATRIX'}
        </button>
      </div>

      {/* Threats / Alerts List */}
      <div className="flex-1 p-4 overflow-y-auto w-full">
         <div className="flex items-center justify-between mb-3">
           <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
             <AlertTriangle size={12} className="text-amber-500" />
             Active Threats
           </h3>
           <span className="text-[9px] bg-emerald-900/50 border border-emerald-800/50 px-1.5 py-0.5 rounded text-emerald-300">LIVE</span>
         </div>
         
         <div className="flex flex-col gap-3">
            {checkpoints.length === 0 && (
               <div className="text-xs text-slate-500 text-center p-4 border border-dashed border-slate-700/50 rounded-lg">
                 No critical conjunction hotspots detected.
               </div>
            )}
            {checkpoints.map((cp: any, i: number) => {
              const impactEnergyMj = (Math.max(1, 15000 / cp.distKm) * 8.5).toFixed(1); // Synthetic kinetic approximation
              const probability = (1 / (Math.max(1, cp.distKm) * 50)).toExponential(2);
              const isCritical = cp.distKm < 500;
              
              return (
                <div key={i} className={`p-3 rounded-lg border flex flex-col gap-2 ${isCritical ? 'bg-red-900/10 border-red-800/30 shadow-[0_0_15px_rgba(239,68,68,0.05)]' : 'bg-amber-900/10 border-amber-800/30'}`}>
                  {/* Header */}
                  <div className="flex justify-between items-center bg-slate-900/50 -mx-3 -mt-3 p-2 rounded-t-lg border-b border-slate-700/30">
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase ${isCritical ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}`}>
                      {isCritical ? 'CRITICAL TCA' : 'WARNING TCA'}
                    </span>
                    <span className="text-[10px] text-slate-400 font-mono">T+{cp.timeOffset} MIN</span>
                  </div>
                  
                  {/* Metrics Grid */}
                  <div className="grid grid-cols-2 gap-2 mt-1">
                    <div className="bg-slate-900/80 border border-slate-700/50 py-1.5 px-2 rounded flex flex-col">
                      <span className="text-[9px] text-slate-500 mb-0.5">Miss Distance</span>
                      <span className={`font-mono text-[11px] font-bold ${isCritical ? 'text-red-400' : 'text-amber-400'}`}>
                        {cp.distKm.toFixed(1)} km
                      </span>
                    </div>
                    <div className="bg-slate-900/80 border border-slate-700/50 py-1.5 px-2 rounded flex flex-col">
                      <span className="text-[9px] text-slate-500 mb-0.5">Collision Prob.</span>
                      <span className="font-mono text-slate-300 text-[11px]">{probability}</span>
                    </div>
                    <div className="bg-slate-900/80 border border-slate-700/50 py-1.5 px-2 rounded flex flex-col col-span-2 text-center">
                      <span className="text-[9px] text-slate-500 mb-0.5">Est. Impact Energy (Rel. Vel)</span>
                      <span className="font-mono text-blue-300 text-[11px]">{impactEnergyMj} MJ/kg</span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="grid grid-cols-2 gap-2 mt-1">
                    <button 
                      onClick={() => setFocusTarget(focusTarget === cp.pos ? null : cp.pos)}
                      className={`text-[9px] font-bold px-2 py-1.5 rounded transition-colors flex items-center justify-center gap-1 border ${focusTarget === cp.pos ? 'bg-emerald-600/80 hover:bg-emerald-500 text-white border-emerald-500' : 'bg-slate-700 hover:bg-slate-600 text-slate-200 border-slate-500/50'}`}
                    >
                      <Orbit size={10} /> {focusTarget === cp.pos ? 'UNFOCUS' : 'AUTO-FOCUS'}
                    </button>
                    <button 
                      onClick={() => onCommandAgent(`Analyze trajectory and spawn Vizier study for TCA at T+${cp.timeOffset}m.`)}
                      className="bg-indigo-600/80 hover:bg-indigo-500 text-white text-[9px] font-bold px-2 py-1.5 rounded transition-colors flex items-center justify-center gap-1 border border-indigo-400/50"
                    >
                      <Zap size={10} /> VIZIER STUDY
                    </button>
                  </div>

                </div>
              );
            })}
         </div>
      </div>
        </div>
      ) : (
        <div className="p-4 flex flex-col flex-1 min-h-0 w-full overflow-hidden">
           <div className="relative mb-3 shrink-0">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input 
                type="text" 
                placeholder="Search name or ID..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="bg-slate-900/80 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-xs text-slate-200 w-full focus:outline-none focus:border-indigo-500 transition-colors"
              />
           </div>
           
           <div className="flex-1 overflow-y-auto pr-1 space-y-2">
              {loadingCatalog ? (
                 <div className="flex flex-col items-center justify-center h-32 gap-3">
                   <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
                   <div className="text-slate-400 text-xs animate-pulse">Loading catalog...</div>
                 </div>
              ) : filteredCatalog.map((sat, i) => (
                 <div key={i} className="bg-slate-800/80 border border-slate-700 p-3 rounded-lg hover:border-indigo-500/50 cursor-pointer transition-colors group"
                      onClick={() => {
                          setTrackInput(sat.NORAD_CAT_ID);
                          handleMarkSatellite(sat.NORAD_CAT_ID);
                          setActiveTab('matrix');
                      }}
                 >
                    <div className="flex justify-between items-start mb-1">
                       <div className="font-bold text-slate-200 text-xs truncate pr-2 group-hover:text-indigo-300 transition-colors uppercase">
                          {sat.OBJECT_NAME || "UNKNOWN"}
                       </div>
                       <span className="text-[10px] bg-slate-900 px-1.5 py-0.5 rounded text-slate-400 font-mono">
                          {sat.NORAD_CAT_ID}
                       </span>
                    </div>
                    <div className="flex justify-between text-[10px] text-slate-500">
                       <span>Type: {sat.OBJECT_TYPE || "N/A"}</span>
                       <span>Period: {sat.PERIOD ? parseFloat(sat.PERIOD).toFixed(1) + 'm' : "N/A"}</span>
                    </div>
                 </div>
              ))}
              {filteredCatalog.length === 0 && !loadingCatalog && (
                 <div className="text-center text-slate-500 text-xs py-4">No satellites found.</div>
              )}
           </div>
        </div>
      )}
    </div>
  );
}

// ==============================================
// Vizier Custom Chart Component
// ==============================================
import { useFrame } from '@react-three/fiber';

function CameraController({ focusTarget, controlsRef }: { focusTarget: THREE.Vector3 | null, controlsRef: any }) {
  useFrame((state) => {
    if (focusTarget && controlsRef.current) {
       controlsRef.current.target.lerp(focusTarget, 0.05);
       
       // Calculate a dynamic viewing position slightly above and outward from the planet
       const viewOffset = focusTarget.clone().normalize().multiplyScalar(focusTarget.length() + 0.5);
       state.camera.position.lerp(viewOffset, 0.05);
       controlsRef.current.update();
    }
  });
  return null;
}

function VizierDashboard({ data, onApplyEvasion }: { data: VizierData, onApplyEvasion: () => void }) {
  const maxDv = Math.max(...data.trials.map(t => t.dv));
  
  return (
    <div className="mt-4 bg-slate-900 border border-slate-700 rounded-lg p-4 font-sans text-sm shadow-inner w-[320px]">
      <div className="flex items-center gap-2 mb-3 text-emerald-400 border-b border-slate-800 pb-2">
        <Zap size={16} className="animate-pulse" />
        <span className="font-semibold text-xs tracking-wider uppercase">Vizier Optimization Study</span>
      </div>
      
      <p className="text-slate-400 text-[11px] mb-4">
        Exploring cost-effective Collision Avoidance Maneuvers for SAT-{data.target}. 
        Study ID: <span className="font-mono text-slate-500">{data.study_id}</span>
      </p>

      {/* Bar Chart Storytelling */}
      <div className="mb-4">
        <h4 className="text-slate-300 text-xs font-semibold mb-2">Convergence History (Cost vs Trial)</h4>
        <div className="flex items-end gap-2 h-24 pt-4 border-l border-b border-slate-700 pb-1 pl-1">
          {data.trials.map((trial, i) => {
             const heightPct = Math.max((trial.dv / maxDv) * 100, 5);
             const isOptimal = i === data.trials.length - 1; // Assuming last is optimal for styling
             return (
               <div key={i} className="flex-1 flex flex-col items-center justify-end group">
                 <div className="text-[9px] text-slate-500 font-mono opacity-0 group-hover:opacity-100 transition-opacity mb-1">
                   {trial.dv.toFixed(2)}m/s
                 </div>
                 <div 
                   className={`w-full rounded-t-sm transition-all duration-500 ${isOptimal ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-indigo-500/60'}`} 
                   style={{ height: `${heightPct}%` }}
                 ></div>
                 <div className="text-[9px] text-slate-600 mt-1 font-mono">T{trial.iter}</div>
               </div>
             )
          })}
        </div>
      </div>

      <div className="bg-slate-800/50 rounded flex justify-between p-3 mb-4 border border-slate-700">
        <div>
          <div className="text-[10px] text-slate-500 uppercase">Optimal Delta-V</div>
          <div className="font-mono text-emerald-400 text-lg">{data.optimal.dv_ms.toFixed(2)} <span className="text-[10px]">m/s</span></div>
        </div>
        <div className="text-right">
          <div className="text-[10px] text-slate-500 uppercase">Time To Maneuver</div>
          <div className="font-mono text-slate-300 text-lg">{(data.optimal.dt_s / 3600).toFixed(1)} <span className="text-[10px]">hrs to TCA</span></div>
        </div>
      </div>

      <button 
        onClick={onApplyEvasion}
        className="w-full bg-gradient-to-r from-emerald-600 to-emerald-500 hover:from-emerald-500 hover:to-emerald-400 text-white text-xs font-bold py-2 rounded shadow flex items-center justify-center gap-2 transition-all"
      >
        <CheckCircle2 size={14} /> Commit Maneuver to System
      </button>
    </div>
  );
}

// ==============================================
// Agent Message Parser
// ==============================================
function parseAgentMessage(text: string): { pureText: string, vizierData: VizierData | null } {
  const jsonMatch = text.match(/```json\n([\s\S]*?)\n```/);
  if (!jsonMatch) return { pureText: text, vizierData: null };
  
  try {
    const rawJson = jsonMatch[1];
    const data = JSON.parse(rawJson);
    if (data.type === "VIZIER_STORY") {
      const pureText = text.replace(/```json\n[\s\S]*?\n```/, '').trim();
      return { pureText, vizierData: data as VizierData };
    }
  } catch (e) {
    console.warn("Failed to parse agent json", e);
  }
  return { pureText: text, vizierData: null };
}

function AgentPane({ onApplyEvasion, externalCommand }: { onApplyEvasion: () => void, externalCommand: string }) {
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    { role: 'agent', text: "Orbit Intelligence ADK online. I've detected a high-risk conjunction for SPACEMOBILE-005. Should I spawn a Vizier optimization study to calculate evasion maneuvers?" }
  ]);

  const handleSend = async (overrideMsg?: string) => {
    const userMessage = overrideMsg || input.trim();
    if (!userMessage || isLoading) return;
    
    setMessages(prev => [...prev, { role: 'user', text: userMessage }]);
    if (!overrideMsg) setInput('');
    setIsLoading(true);
    
    try {
      const res = await fetch("http://localhost:8080/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMessage })
      });
      
      const data = await res.json();
      
      if (data.error) {
        setMessages(prev => [...prev, { 
          role: 'agent', 
          text: `⚠️ Backend Error: ${data.error}. If GCP credentials are not set, the live model call will fail.` 
        }]);
      } else {
         const { pureText, vizierData } = parseAgentMessage(data.response);
         setMessages(prev => [...prev, { 
          role: 'agent', 
          text: pureText,
          vizierData: vizierData
        }]);
      }
    } catch (err) {
      setMessages(prev => [...prev, { 
        role: 'agent', 
        text: `⚠️ Network Error: Could not reach backend at localhost:8080. Ensure the FastAPI server is running in the dissertacao folder.` 
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (externalCommand) {
      handleSend(externalCommand);
    }
  }, [externalCommand]);

  const handleSendAction = () => {
    handleSend();
  };

  return (
    <div className="w-96 flex-shrink-0 bg-slate-800/50 border border-slate-700 rounded-xl flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 p-4 border-b border-slate-700 bg-slate-800/80">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
          <Settings2 size={16} className="text-white" />
        </div>
        <div>
          <h2 className="font-semibold text-sm">ADK Orchestrator</h2>
          <div className="text-[10px] text-indigo-400 flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse"></div>
            Vertex AI Connected
          </div>
        </div>
      </div>
      
      <div className="flex-1 p-4 overflow-y-auto flex flex-col gap-4 max-h-[calc(100vh-12rem)]">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'} flex-col`}>
             <div className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] p-3 rounded-2xl text-sm whitespace-pre-wrap ${
                  m.role === 'user' 
                    ? 'bg-blue-600 text-white rounded-tr-sm' 
                    : 'bg-slate-700/50 border border-slate-600 text-slate-200 rounded-tl-sm'
                }`}>
                  {m.text}
                </div>
             </div>
             
             {/* If agent returned Vizier Data, render the custom Dashboard */}
             {m.vizierData && (
                <div className="flex justify-start">
                   <VizierDashboard data={m.vizierData} onApplyEvasion={onApplyEvasion} />
                </div>
             )}
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
             <div className="bg-slate-700/50 border border-slate-600 text-slate-400 p-3 rounded-2xl rounded-tl-sm text-sm flex items-center gap-2">
               <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce"></div>
               <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce delay-100"></div>
               <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce delay-200"></div>
             </div>
          </div>
        )}
      </div>

      <div className="p-3 bg-slate-800 border-t border-slate-700">
        <div className="relative">
          <input 
            type="text" 
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSendAction()}
            disabled={isLoading}
            placeholder={isLoading ? "Agent is thinking..." : "Command the ADK Agent..."}
            className="w-full bg-slate-900 border border-slate-600 rounded-lg py-2.5 pl-3 pr-10 text-sm focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-50"
          />
          <button 
            onClick={handleSendAction}
            disabled={isLoading}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 bg-indigo-500 hover:bg-indigo-400 disabled:bg-slate-600 rounded-md transition-colors text-white"
          >
            <Send size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [isEvasive, setIsEvasive] = useState(false);
  const [externalCommand, setExternalCommand] = useState("");

  const [primaryTLE, setPrimaryTLE] = useState<any>(null);
  const [threatTLE, setThreatTLE] = useState<any>(null);
  const [show4D, setShow4D] = useState(false);
  const [trackInput, setTrackInput] = useState('25544');
  const [syncStatus, setSyncStatus] = useState<'idle' | 'syncing' | 'active'>('idle');
  const [timeOffset, setTimeOffset] = useState<number>(0);
  
  // Lift checkpoints and focus target strictly to Root App level for cross-panel syncing
  const [checkpoints, setCheckpoints] = useState<any[]>([]);
  const [focusTarget, setFocusTarget] = useState<THREE.Vector3 | null>(null);
  const [historyTles, setHistoryTles] = useState<any[]>([]);

  useEffect(() => {
    if (show4D) {
      fetch('http://localhost:8080/api/satellites/historical/25544')
        .then(res => res.json())
        .then(data => {
          if (data.history) {
             const hSatrecs = data.history.map((h: any) => {
               try { return satellite.twoline2satrec(h.TLE_LINE1, h.TLE_LINE2); } catch(e) { return null; }
             }).filter(Boolean);
             setHistoryTles(hSatrecs);
          }
        })
        .catch(console.error);
    } else {
      setHistoryTles([]);
    }
  }, [show4D]);

  useEffect(() => {
    // Determine static initial state
    const line1ISS = "1 25544U 98067A   23305.50000000  .00016717  00000-0  30043-3 0  9997";
    const line2ISS = "2 25544  51.6413 135.5323 0004515 224.2343 277.8398 15.49884617422998";
    setPrimaryTLE({ satrec: satellite.twoline2satrec(line1ISS, line2ISS), name: "SPACEMOBILE-005" });

    const line1Deb = "1 49303U 21088A   23305.50000000  .00012345  00000-0  20000-3 0  9991";
    const line2Deb = "2 49303  97.6413 135.5323 0014515 124.2343 077.8398 15.19884617422998";
    setThreatTLE({ satrec: satellite.twoline2satrec(line1Deb, line2Deb), name: "PEGASUS DEB" });
    
    // Auto-mark default
    setSyncStatus('syncing');
    fetch('http://localhost:8080/api/satellites/mark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ norad_id: parseInt('25544') })
    }).finally(() => { setTimeout(() => setSyncStatus('active'), 800); });
  }, []);

  const handleMarkSatellite = (overrideId?: string) => {
    const targetId = overrideId || trackInput;
    setSyncStatus('syncing');
    fetch('http://localhost:8080/api/satellites/mark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ norad_id: parseInt(targetId) })
    })
    .finally(() => {
       setTimeout(() => setSyncStatus('active'), 800);
    });
  };

  const handleApplyEvasion = () => {
    setIsEvasive(true);
  };

  const commandAgent = (cmd: string) => {
     setExternalCommand(cmd);
     setTimeout(() => setExternalCommand(""), 100);
  };

  return (
    <div className="h-screen w-screen bg-slate-900 text-slate-200 overflow-hidden flex flex-col font-sans">
      {/* Top Header */}
      <header className="h-14 border-b border-slate-800 bg-slate-950 flex items-center justify-between px-6 shrink-0 shadow-sm z-20">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 rounded bg-gradient-to-tr from-indigo-500 to-purple-500 shadow-[0_0_10px_rgba(99,102,241,0.5)] flex items-center justify-center">
            <Orbit size={14} className="text-white" />
          </div>
          <h1 className="font-bold text-lg tracking-wide text-slate-100">SafeOnOrbit <span className="font-light text-slate-500 ml-2">Intelligence Center</span></h1>
        </div>
      </header>
      
      {/* Main Workspace */}
      <main className="flex-1 flex gap-4 p-4 overflow-hidden bg-[url('/grid.svg')] bg-center bg-cover border-t border-slate-800/50">
        <IntelligenceSidebar 
          trackInput={trackInput} 
          setTrackInput={setTrackInput}
          handleMarkSatellite={handleMarkSatellite}
          syncStatus={syncStatus}
          show4D={show4D}
          setShow4D={setShow4D}
          primaryName={primaryTLE?.name}
          isEvasive={isEvasive}
          timeOffset={timeOffset}
          setTimeOffset={setTimeOffset}
          checkpoints={checkpoints}
          setFocusTarget={setFocusTarget}
          focusTarget={focusTarget}
          onCommandAgent={commandAgent}
        />
        
        <div className="flex-1 min-w-0 h-full drop-shadow-2xl">
          <Center3DView 
            isEvasive={isEvasive} 
            onCommandAgent={commandAgent} 
            primaryTLE={primaryTLE} 
            threatTLE={threatTLE}
            historyTles={historyTles}
            timeOffset={timeOffset}
            checkpoints={checkpoints}
            setCheckpoints={setCheckpoints}
            focusTarget={focusTarget}
          />
        </div>
        
        <AgentPane onApplyEvasion={handleApplyEvasion} externalCommand={externalCommand} />
      </main>
    </div>
  );
}

export default App;
