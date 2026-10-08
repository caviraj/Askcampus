/**
 * DocStack: The calm floating stack of college documents.
 *
 * Step 0: Stack floats calmly in a quiet room with readable titles.
 * Step 1: An incoming document ("Hostel Regulations") slides in, flipping
 *         status from "Processing" to "Ready".
 * Step 2: The top document lifts and readies to split into strips.
 */
import React, { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import {
  readPalette,
  sheetTexture,
  repaintOnFontsReady,
  Palette,
} from "./textures";
import { easeInOut, mix, phase } from "./useScrollTimeline";

interface DocStackProps {
  progressRef: React.RefObject<number>;
}

export const DocStack: React.FC<DocStackProps> = ({ progressRef }) => {
  const palette = useMemo<Palette>(() => readPalette(), []);

  // Textures for the static stack
  const calTexture = useMemo(
    () =>
      sheetTexture(
        {
          title: "Academic Calendar 2026-27",
          lines: 10,
          accent: true,
        },
        palette,
      ),
    [palette],
  );

  const regTexture = useMemo(
    () =>
      sheetTexture(
        {
          title: "Examination Regulations",
          lines: 12,
          accent: false,
        },
        palette,
      ),
    [palette],
  );

  const codeTexture = useMemo(
    () =>
      sheetTexture(
        {
          title: "Student Code of Conduct",
          lines: 11,
          accent: true,
        },
        palette,
      ),
    [palette],
  );

  // Status-flipping upload document: Processing vs Ready
  const uploadPendingTex = useMemo(
    () =>
      sheetTexture(
        {
          title: "Hostel Guidelines & Leave",
          lines: 10,
          status: { label: "Processing", tone: "pending" },
          accent: true,
        },
        palette,
      ),
    [palette],
  );

  const uploadReadyTex = useMemo(
    () =>
      sheetTexture(
        {
          title: "Hostel Guidelines & Leave",
          lines: 10,
          status: { label: "Ready", tone: "ready" },
          accent: true,
        },
        palette,
      ),
    [palette],
  );

  // Repaint on font load
  React.useEffect(() => {
    const unsubs = [
      repaintOnFontsReady(calTexture),
      repaintOnFontsReady(regTexture),
      repaintOnFontsReady(codeTexture),
      repaintOnFontsReady(uploadPendingTex),
      repaintOnFontsReady(uploadReadyTex),
    ];
    return () => unsubs.forEach((u) => u());
  }, [
    calTexture,
    regTexture,
    codeTexture,
    uploadPendingTex,
    uploadReadyTex,
  ]);

  const groupRef = useRef<THREE.Group>(null);
  const uploadMeshRef = useRef<THREE.Mesh>(null);
  const uploadMatRef = useRef<THREE.MeshStandardMaterial>(null);

  // Geometry dimensions for standard document sheets
  const sheetGeom = useMemo(() => new THREE.PlaneGeometry(2.4, 3.2), []);

  useFrame((state) => {
    if (!groupRef.current) return;
    const p = progressRef.current ?? 0;
    const time = state.clock.getElapsedTime();

    // Base subtle floating breathing motion
    const floatY = Math.sin(time * 0.8) * 0.05;
    const floatRot = Math.cos(time * 0.6) * 0.015;

    // Step 0 to 1: Active and centered
    // Step 2: Stack shifts back/left as strips take focus
    // Step 3+: Diminishes / recedes
    const step = p * 5; // 0 to 5

    // Global stack position based on story
    const stackShiftX = mix(0, -1.8, easeInOut(phase(step, 1.2, 2.2)));
    const stackShiftZ = mix(0, -1.2, easeInOut(phase(step, 1.2, 2.2)));
    const stackFade = mix(1, 0.25, easeInOut(phase(step, 2.0, 3.2)));

    groupRef.current.position.x = stackShiftX;
    groupRef.current.position.y = floatY;
    groupRef.current.position.z = stackShiftZ;
    groupRef.current.rotation.z = floatRot;

    // Upload animation (Step 1: step 0.8 to 1.8)
    if (uploadMeshRef.current && uploadMatRef.current) {
      const uploadP = easeInOut(phase(step, 0.7, 1.4));
      // Slide in from top-right (+X, +Y, +Z)
      const startX = 3.2;
      const startY = 2.5;
      const startZ = 1.0;
      const endX = 0;
      const endY = 0;
      const endZ = 0.08; // Sits on top of stack

      uploadMeshRef.current.position.x = mix(startX, endX, uploadP);
      uploadMeshRef.current.position.y = mix(startY, endY, uploadP);
      uploadMeshRef.current.position.z = mix(startZ, endZ, uploadP);
      uploadMeshRef.current.rotation.z = mix(0.12, 0, uploadP);

      // Status flip from Processing to Ready around uploadP ~ 0.8
      const isReady = uploadP >= 0.75;
      const targetTex = isReady ? uploadReadyTex : uploadPendingTex;
      if (uploadMatRef.current.map !== targetTex) {
        uploadMatRef.current.map = targetTex;
        uploadMatRef.current.needsUpdate = true;
      }

      // Step 2: this upload sheet dissolves as it splits into strips
      const splitP = phase(step, 1.8, 2.3);
      uploadMatRef.current.opacity = mix(1, 0, easeInOut(splitP)) * stackFade;
      uploadMeshRef.current.visible = uploadMatRef.current.opacity > 0.01;
    }
  });

  return (
    <group ref={groupRef}>
      {/* Base Sheet 1: Calendar (bottom of stack) */}
      <mesh
        geometry={sheetGeom}
        position={[-0.08, -0.06, -0.06]}
        rotation={[0, 0, -0.04]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          map={calTexture ?? undefined}
          roughness={0.7}
          metalness={0.05}
        />
      </mesh>

      {/* Base Sheet 2: Regulations (middle of stack) */}
      <mesh
        geometry={sheetGeom}
        position={[0.04, -0.02, -0.03]}
        rotation={[0, 0, 0.03]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          map={regTexture ?? undefined}
          roughness={0.7}
          metalness={0.05}
        />
      </mesh>

      {/* Base Sheet 3: Code of Conduct */}
      <mesh
        geometry={sheetGeom}
        position={[0, 0, 0]}
        rotation={[0, 0, 0]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          map={codeTexture ?? undefined}
          roughness={0.7}
          metalness={0.05}
        />
      </mesh>

      {/* Uploading Sheet: Hostel Guidelines with flipping status */}
      <mesh
        ref={uploadMeshRef}
        geometry={sheetGeom}
        position={[3.2, 2.5, 1.0]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          ref={uploadMatRef}
          map={uploadPendingTex ?? undefined}
          transparent
          roughness={0.65}
          metalness={0.05}
        />
      </mesh>
    </group>
  );
};
