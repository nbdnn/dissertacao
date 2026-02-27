import numpy as np
import matplotlib.pyplot as plt
import os

output_dir = '/home/guima/dissertacao/docs/figuras/'
os.makedirs(output_dir, exist_ok=True)

fig = plt.figure(figsize=(10, 8))
ax = fig.add_subplot(111, projection='3d')

# Dimensões do elipsoide B_safe (1km x 5km x 1km)
rx, ry, rz = 1.0, 5.0, 1.0

u = np.linspace(0, 2 * np.pi, 50)
v = np.linspace(0, np.pi, 50)
x = rx * np.outer(np.cos(u), np.sin(v))
y = ry * np.outer(np.sin(u), np.sin(v))
z = rz * np.outer(np.ones_like(u), np.cos(v))

# Plot da superfície
ax.plot_surface(x, y, z, color='b', alpha=0.3, rstride=2, cstride=2, linewidth=0.1, edgecolor='k')

# Marcação do Satélite Primário no centro
ax.scatter([0], [0], [0], color='r', s=100, label='Satélite Primário')

ax.set_xlabel('R (Radial) [km]', fontsize=11, labelpad=15)
ax.set_ylabel('S (Along-track) [km]', fontsize=11, labelpad=15)
ax.set_zlabel('W (Cross-track) [km]', fontsize=11, labelpad=15)
ax.set_title(r'Elipsoide de Incerteza $\mathcal{B}_{safe}$ em referencial RSW', fontsize=14, pad=20)

ax.set_xticks([-2, -1, 0, 1, 2])
ax.set_yticks([-6, -3, 0, 3, 6])
ax.set_zticks([-2, -1, 0, 1, 2])

ax.tick_params(axis='x', pad=5)
ax.tick_params(axis='y', pad=5)
ax.tick_params(axis='z', pad=10)

ax.legend(loc='upper left')

# Ajuste de limites e aspecto
ax.set_xlim(-2, 2)
ax.set_ylim(-6, 6)
ax.set_zlim(-2, 2)
ax.set_box_aspect([1, 3, 1]) 

out_file = os.path.join(output_dir, 'ellipsoid_3d.png')
plt.savefig(out_file, dpi=300, bbox_inches='tight')
print(f"Gráfico salvo em: {out_file}")
