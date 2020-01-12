#!/usr/bin/env python
import numpy as np
from nav_msgs.msg import OccupancyGrid


def send_map_ros_msg(landmarks, empty_landmarks, publisher, resolution = 0.01, width = 2048, height = 2048):
    map_msg = OccupancyGrid()
    map_msg.header.frame_id = 'map'
    map_msg.info.resolution = resolution
    map_msg.info.width = width
    map_msg.info.height = height

    data = -np.ones(shape = (width,height))
    for ii in range(len(landmarks)):
        on_x = landmarks[ii,0] // resolution + width  // 2
        on_y = landmarks[ii,1] // resolution + height // 2
        if on_x < width and on_x > 0 and on_y < height and on_y > 0:
            data[int(on_x), int(on_y)] = 100

    for ii in range(len(empty_landmarks)):
        off_x = empty_landmarks[ii,0] // resolution + width  // 2
        off_y = empty_landmarks[ii,1] // resolution + height // 2
        if off_x < width and off_x > 0 and off_y < height and off_y > 0:
            data[int(off_x), int(off_y)] = 0

    data_out = data.reshape((-1))
    map_msg.data = data_out
    publisher.publish(map_msg)
    
def rotate_map_parallel(map, T):
    c ,s = np.cos(T[:,2]) , np.sin(T[:,2])
    R = np.array(((c,-s), (s, c)))
    Tmap = np.matmul(map,R)
    rot_map = np.add(np.transpose(Tmap, (1,2,0)), T[:,0:2])
    return rot_map

def rotate_map(map, T):
    c ,s = np.cos(T[2]) , np.sin(T[2])
    R = np.array(((c,-s), (s, c))) 
    rot_map = np.matmul(map,R) + T[0:2]
    return rot_map

def likelihood(target_map_rotated, origin_map_nbrs, var, origin_empty_map_nbrs=None , res = 0.01):
    if origin_empty_map_nbrs is None:
        d, _ = origin_map_nbrs.kneighbors(target_map_rotated)
        p = np.mean((1/(np.sqrt(2*np.pi*var)))*np.exp(-np.power(d,2)/(2*var))) + 1e-200
    else:
        d, _ = origin_map_nbrs.kneighbors(target_map_rotated)
        d_empty, _ = origin_empty_map_nbrs.kneighbors(target_map_rotated)
        is_bad = d_empty > res 
        #print(np.mean(is_bad))
        p = np.mean(np.multiply(is_bad,(1/(np.sqrt(2*np.pi*var)))*np.exp(-np.power(d,2)/(2*var)))) + 1e-200
        #p = np.mean(is_bad)*p
    return p

def likelihood_parallel(T, target_map, origin_map_nbrs, var):
    target_map_rotated = rotate_map_parallel(target_map, T)
    d, _ = origin_map_nbrs.kneighbors(target_map_rotated.reshape((-1,2)))
    p = np.mean((1/(np.sqrt(2*np.pi*var)))*np.exp(-np.power(d,2)/(2*var)), axis=0)
    p = p/np.sum(p)
    return p


class ParticleFilterMapMatcher():
    def __init__(self,init_origin_map_nbrs, init_target_map, Np = 1000, N_history = 5,  N_theta = 50, N_x = 20, N_y = 20, R_var = 0.1):
        self.Np = Np
        self.R_var = R_var
        self.N_history = N_history
        self.filter = np.arange(3,N_history+3,dtype=np.float32)
        temp_X = []
        angles = np.linspace(0 , 2*np.pi ,N_theta )
        xRange = np.linspace(-10 , 10 , N_x) 
        yRange = np.linspace(-10 , 10 ,N_y) 
        x0 = [xRange[np.random.randint(N_x)] ,yRange[np.random.randint(N_y)], angles[np.random.randint(N_theta)]]
        tempMap = rotate_map(init_target_map, x0)
        w0 = likelihood(tempMap, init_origin_map_nbrs, self.R_var)
        temp_X.append(x0)
        i = 0
        print("Initilizing particles...")
        while i < (N_theta*N_x*N_y):
            xt = [xRange[np.random.randint(N_x)],
                yRange[np.random.randint(N_y)],
                angles[np.random.randint(N_theta)]]
            tempMap = rotate_map(init_target_map, xt)
            wt = likelihood(tempMap, init_origin_map_nbrs, self.R_var)
            if wt>w0:
                temp_X.append(xt)
                x0 = xt
                w0 = wt
            elif np.random.binomial(1, wt/w0) == 1:
                temp_X.append(xt)
                x0 = xt
                w0 = wt
            elif np.random.binomial(1, 0.5) == 1:
                temp_X.append(xt)
                x0 = xt
                w0 = wt
            else:
                x = x0
                x[0] = x[0] + np.random.normal(0.0, 0.1)
                x[1] = x[1] + np.random.normal(0.0, 0.1)
                x[2] = x[2] + np.random.normal(0.0, 0.1) + np.random.choice(a = 4,p = [0.4,0.2,0.2,0.2] )*0.5*np.pi
                x[2] = np.remainder(x[2],2*np.pi)
                temp_X.append(x)
            i += 1
        self.X = np.array(temp_X[-Np:])
        self.W = np.ones((Np,N_history))
        self.indicate = 0
        print("Initilizing done with "+str(Np)+" samples out of "+str(len(temp_X)))

    def predict(self):
        self.X[:,0:2] = self.X[:,0:2] + np.random.normal(0.0, 0.05, size=self.X[:,0:2].shape)
        self.X[:,2] = self.X[:,2] + np.random.normal(0.0, 0.01, size=self.X[:,2].shape)
        self.X[:,2] = np.remainder(self.X[:,2],2*np.pi)

    def update(self, target_map, origin_map_nbrs, origin_empty_map_nbrs, res = 0.01):
        for i in range(self.Np):
            tempMap = rotate_map(target_map, self.X[i])
            if self.indicate > 0:
                self.W[i, self.indicate] = self.W[i, self.indicate - 1] * likelihood(tempMap, origin_map_nbrs, self.R_var, origin_empty_map_nbrs, res)
            else:
                self.W[i, self.indicate] = likelihood(tempMap, origin_map_nbrs, self.R_var, origin_empty_map_nbrs, res)
        self.indicate += 1
    
    def update_parallel(self, target_map, origin_map_nbrs, origin_empty_map_nbrs, res = 0.01):
        L = likelihood_parallel(self.X, target_map, origin_map_nbrs, self.R_var)
        if self.indicate > 0:
            self.W[:, self.indicate] = self.W[:, self.indicate - 1] * L
        else:
            self.W[:, self.indicate] = L
        self.indicate += 1

    def resample(self):
        print("performing resample!")
        p = np.dot(self.W, self.filter)
        p = p/np.sum(p)
        self.X_map = self.X[np.argmax(p)]
        idxs = np.random.choice(a = self.Np, size = self.Np,p = p)
        self.X = self.X[idxs]
        self.X[:,0] = self.X[:,0] + np.random.normal(0.0, 0.3, size=self.X[:,0].shape) + np.random.randint(-1,2) * np.random.choice(a = 5, size = self.X[:,0].shape,p = [0.7,0.1,0.1,0.1, 0.0] )*2.0
        self.X[:,1] = self.X[:,1] + np.random.normal(0.0, 0.3, size=self.X[:,1].shape) + np.random.randint(-1,2) * np.random.choice(a = 5, size = self.X[:,1].shape,p = [0.7,0.1,0.1,0.1, 0.0]  )*2.0
        self.X[:,2] = self.X[:,2] + np.random.normal(0.0, 0.1, size=self.X[:,2].shape) + np.random.choice(a = 4, size = self.X[:,2].shape,p = [0.7,0.1,0.1,0.1] )*0.5*np.pi
        self.X[:,2] = np.remainder(self.X[:,2],2*np.pi)
        self.indicate = 0

   