import React, { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import {
  questionCardTexture,
  answerCardTexture,
  refusalCardTexture,
  readPalette,
} from './textures';
import { phase, mix, mixEased } from './useScrollTimeline';

interface AnswerCardProps {
  progressRef: React.MutableRefObject<number>;
  darkMode?: boolean;
}

export const AnswerCard: React.FC<AnswerCardProps> = ({ progressRef, darkMode = false }) => {
  const palette = useMemo(() => readPalette(darkMode), [darkMode]);

  // Question 1 Texture (Step 4 & 5)
  const q1Texture = useMemo(
    () => questionCardTexture(palette, 'When is the deadline to drop a spring course?'),
    [palette]
  );

  // Answer Card Texture (Step 5)
  const ansTexture = useMemo(
    () =>
      answerCardTexture(
        palette,
        'Academic Regulations 2025–26',
        'Courses dropped before the end of Week 4',
        'will not appear on your permanent academic transcript. After Week 4, a grade of W is recorded.'
      ),
    [palette]
  );

  // Question 2 Texture (Step 6)
  const q2Texture = useMemo(
    () => questionCardTexture(palette, 'Can I bring my pet iguana to the student dorms?'),
    [palette]
  );

  // Refusal Card Texture (Step 6 - Drops into tray)
  const refusalTexture = useMemo(
    () =>
      refusalCardTexture(
        palette,
        'No college policy covers exotic pets. This inquiry has been routed to Student Housing staff.'
      ),
    [palette]
  );

  // Refs for 3D groups
  const q1GroupRef = useRef<THREE.Group>(null);
  const ansGroupRef = useRef<THREE.Group>(null);
  const q2GroupRef = useRef<THREE.Group>(null);
  const refusalGroupRef = useRef<THREE.Group>(null);

  // Geometry
  const cardGeo = useMemo(() => new THREE.PlaneGeometry(1.7, 1.15), []);
  const questionGeo = useMemo(() => new THREE.PlaneGeometry(1.6, 0.65), []);
  const refusalGeo = useMemo(() => new THREE.PlaneGeometry(1.5, 0.75), []);

  useFrame(() => {
    const p = progressRef.current;

    // 1. Question 1 (Step 4: p in [3, 4], fades out in Step 5: p in [4, 5])
    if (q1GroupRef.current) {
      if (p >= 2.8 && p <= 4.8) {
        q1GroupRef.current.visible = true;
        const enter = phase(p, 2.8, 3.2);
        const exit = phase(p, 4.4, 4.8);

        const x = mix(-2.2, -1.2, mixEased(enter));
        const y = mix(1.1, 0.9, mixEased(enter));
        const z = mix(-0.2, 0.35, mixEased(enter));
        const scale = mix(0.7, 1.0, mixEased(enter)) * (1.0 - exit);

        q1GroupRef.current.position.set(x, y, z);
        q1GroupRef.current.scale.set(scale, scale, scale);
        q1GroupRef.current.rotation.set(0.04, 0.08, -0.02);
      } else {
        q1GroupRef.current.visible = false;
      }
    }

    // 2. Answer Card (Step 5: p in [4, 5], fades out in Step 6: p in [5, 6])
    if (ansGroupRef.current) {
      if (p >= 3.9 && p <= 5.4) {
        ansGroupRef.current.visible = true;
        const enter = phase(p, 3.9, 4.4);
        const exit = phase(p, 5.0, 5.4);

        const x = mix(1.6, 0.85, mixEased(enter));
        const y = mix(-0.2, 0.15, mixEased(enter));
        const z = mix(0.1, 0.45, mixEased(enter));
        const scale = mix(0.75, 1.0, mixEased(enter)) * (1.0 - exit);

        ansGroupRef.current.position.set(x, y, z);
        ansGroupRef.current.scale.set(scale, scale, scale);
        ansGroupRef.current.rotation.set(-0.02, -0.05, 0.01);
      } else {
        ansGroupRef.current.visible = false;
      }
    }

    // 3. Question 2 (Step 6: p in [5, 6])
    if (q2GroupRef.current) {
      if (p >= 4.85) {
        q2GroupRef.current.visible = true;
        const enter = phase(p, 4.85, 5.3);

        const x = mix(-2.0, -1.0, mixEased(enter));
        const y = mix(1.2, 0.85, mixEased(enter));
        const z = mix(-0.2, 0.35, mixEased(enter));
        const scale = mix(0.7, 1.0, mixEased(enter));

        q2GroupRef.current.position.set(x, y, z);
        q2GroupRef.current.scale.set(scale, scale, scale);
        q2GroupRef.current.rotation.set(0.05, 0.06, -0.02);
      } else {
        q2GroupRef.current.visible = false;
      }
    }

    // 4. Refusal Card (Step 6: p in [5, 6] - Drops into Unanswered Tray at x=0.7, y=-0.85, z=0.05)
    if (refusalGroupRef.current) {
      if (p >= 5.15) {
        refusalGroupRef.current.visible = true;
        const drop = phase(p, 5.2, 5.85);

        // Starts high at y=0.5, drops into tray at y=-0.78 with realistic slight tilt
        const x = mix(0.65, 0.72, mixEased(drop));
        const y = mix(0.6, -0.74, mixEased(drop));
        const z = mix(0.4, 0.08, mixEased(drop));
        const rotX = mix(-0.1, -0.35, mixEased(drop));
        const rotY = mix(0.1, 0.04, mixEased(drop));
        const rotZ = mix(0.05, -0.02, mixEased(drop));
        const scale = mix(0.85, 0.95, mixEased(drop));

        refusalGroupRef.current.position.set(x, y, z);
        refusalGroupRef.current.rotation.set(rotX, rotY, rotZ);
        refusalGroupRef.current.scale.set(scale, scale, scale);
      } else {
        refusalGroupRef.current.visible = false;
      }
    }
  });

  return (
    <group>
      {/* Question 1 Card */}
      <group ref={q1GroupRef} visible={false}>
        <mesh geometry={questionGeo} castShadow receiveShadow>
          <meshStandardMaterial
            map={q1Texture}
            roughness={0.9}
            metalness={0.02}
            side={THREE.DoubleSide}
          />
        </mesh>
        {/* Subtle drop card back */}
        <mesh position={[0, 0, -0.005]}>
          <planeGeometry args={[1.61, 0.66]} />
          <meshBasicMaterial color={palette.rule} />
        </mesh>
      </group>

      {/* Answer Card with Highlight Phrase */}
      <group ref={ansGroupRef} visible={false}>
        <mesh geometry={cardGeo} castShadow receiveShadow>
          <meshStandardMaterial
            map={ansTexture}
            roughness={0.88}
            metalness={0.02}
            side={THREE.DoubleSide}
          />
        </mesh>
        <mesh position={[0, 0, -0.006]}>
          <planeGeometry args={[1.71, 1.16]} />
          <meshBasicMaterial color={palette.rule} />
        </mesh>
      </group>

      {/* Question 2 Card (Fallback) */}
      <group ref={q2GroupRef} visible={false}>
        <mesh geometry={questionGeo} castShadow receiveShadow>
          <meshStandardMaterial
            map={q2Texture}
            roughness={0.9}
            metalness={0.02}
            side={THREE.DoubleSide}
          />
        </mesh>
        <mesh position={[0, 0, -0.005]}>
          <planeGeometry args={[1.61, 0.66]} />
          <meshBasicMaterial color={palette.rule} />
        </mesh>
      </group>

      {/* Refusal Card ("Not in the documents" dropping into tray) */}
      <group ref={refusalGroupRef} visible={false}>
        <mesh geometry={refusalGeo} castShadow receiveShadow>
          <meshStandardMaterial
            map={refusalTexture}
            roughness={0.88}
            metalness={0.02}
            side={THREE.DoubleSide}
          />
        </mesh>
        <mesh position={[0, 0, -0.005]}>
          <planeGeometry args={[1.51, 0.76]} />
          <meshBasicMaterial color={palette.rule} />
        </mesh>
      </group>
    </group>
  );
};
