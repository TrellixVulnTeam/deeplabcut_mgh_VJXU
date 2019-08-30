'''
Adapted from original predict.py by Eldar Insafutdinov's implementation of [DeeperCut](https://github.com/eldar/pose-tensorflow)

Source: DeeperCut by Eldar Insafutdinov
https://github.com/eldar/pose-tensorflow


To do faster inference on videos:

"On the inference speed and video-compression robustness of DeepLabCut"
Alexander Mathis & Richard Warren
doi: https://doi.org/10.1101/457242
See https://www.biorxiv.org/content/early/2018/10/30/457242
'''

import numpy as np
import tensorflow as tf
vers = (tf.__version__).split('.')
if int(vers[0])==1 and int(vers[1])>12:
    TF=tf.compat.v1
else:
    TF=tf
from deeplabcut.pose_estimation_tensorflow.nnet.net_factory import pose_net

def setup_pose_prediction(cfg):
    TF.reset_default_graph()
    inputs = TF.placeholder(tf.float32, shape=[cfg.batch_size   , None, None, 3])
    net_heads = pose_net(cfg).test(inputs)
    outputs = [net_heads['part_prob']]
    if cfg.location_refinement:
        outputs.append(net_heads['locref'])

    restorer = TF.train.Saver()
    sess = TF.Session()
    sess.run(TF.global_variables_initializer())
    sess.run(TF.local_variables_initializer())

    # Restore variables from disk.
    restorer.restore(sess, cfg.init_weights)

    return sess, inputs, outputs

def extract_cnn_output(outputs_np, cfg):
    ''' extract locref + scmap from network '''
    scmap = outputs_np[0]
    scmap = np.squeeze(scmap)
    locref = None
    if cfg.location_refinement:
        locref = np.squeeze(outputs_np[1])
        shape = locref.shape
        locref = np.reshape(locref, (shape[0], shape[1], -1, 2))
        locref *= cfg.locref_stdev
    if len(scmap.shape)==2: #for single body part!
        scmap=np.expand_dims(scmap,axis=2)
    return scmap, locref

def argmax_pose_predict(scmap, offmat, stride):
    """Combine scoremat and offsets to the final pose."""
    num_joints = scmap.shape[2]
    pose = []
    for joint_idx in range(num_joints):
        maxloc = np.unravel_index(np.argmax(scmap[:, :, joint_idx]),
                                  scmap[:, :, joint_idx].shape)
        offset = np.array(offmat[maxloc][joint_idx])[::-1]
        pos_f8 = (np.array(maxloc).astype('float') * stride + 0.5 * stride +
                  offset)
        pose.append(np.hstack((pos_f8[::-1],
                               [scmap[maxloc][joint_idx]])))
    return np.array(pose)

def getpose(image, cfg, sess, inputs, outputs, outall=False):
    ''' Extract pose '''
    im=np.expand_dims(image, axis=0).astype(float)
    outputs_np = sess.run(outputs, feed_dict={inputs: im})
    scmap, locref = extract_cnn_output(outputs_np, cfg)
    pose = argmax_pose_predict(scmap, locref, cfg.stride)
    if outall:
        return scmap, locref, pose
    else:
        return pose

## Functions below implement are for batch sizes > 1:
def extract_cnn_outputmulti(outputs_np, cfg):
    ''' extract locref + scmap from network
    Dimensions: image batch x imagedim1 x imagedim2 x bodypart'''
    scmap = outputs_np[0]
    locref = None
    if cfg.location_refinement:
        locref =outputs_np[1]
        shape = locref.shape
        locref = np.reshape(locref, (shape[0], shape[1],shape[2], -1, 2))
        locref *= cfg.locref_stdev
    if len(scmap.shape)==2: #for single body part!
        scmap=np.expand_dims(scmap,axis=2)
    return scmap, locref


def getposeNP(image, cfg, sess, inputs, outputs, outall=False):
    ''' Adapted from DeeperCut, performs numpy-based faster inference on batches.
	Introduced in https://www.biorxiv.org/content/10.1101/457242v1 '''
    outputs_np = sess.run(outputs, feed_dict={inputs: image})

    scmap, locref = extract_cnn_outputmulti(outputs_np, cfg) #processes image batch.
    #scmap_imgs = np.multiply(image, scmap_imgs)
    batchsize,ny,nx,num_joints = scmap.shape

    #Combine scoremat and offsets to the final pose.
    LOCREF=locref.reshape(batchsize,nx*ny,num_joints,2)
    MAXLOC=np.argmax(scmap.reshape(batchsize,nx*ny,num_joints),axis=1)
    Y,X=np.unravel_index(MAXLOC,dims=(ny,nx))
    DZ=np.zeros((batchsize,num_joints,3))
    for l in range(batchsize):
        for k in range(num_joints):
            DZ[l,k,:2]=LOCREF[l,MAXLOC[l,k],k,:]
            DZ[l,k,2]=scmap[l,Y[l,k],X[l,k],k]

    scmap_loc = np.zeros_like(scmap)
    for idx, sc in enumerate(scmap):
        for jt in range(scmap.shape[-1]):
            jmax = np.amax(sc[:, :, jt])
            scmap_loc[idx, :, :, jt] = scmap[idx, :, :, jt] / jmax * 255
    scmap_imgs = np.sum(scmap_loc, axis=-1)
    
    X=X.astype('float32')*cfg.stride+.5*cfg.stride+DZ[:,:,0]
    Y=Y.astype('float32')*cfg.stride+.5*cfg.stride+DZ[:,:,1]
    pose = np.empty((cfg['batch_size'], cfg['num_joints']*3), dtype=X.dtype)
    pose[:,0::3] = X
    pose[:,1::3] = Y
    pose[:,2::3] = DZ[:,:,2] #P
    if outall:
        return scmap_imgs, locref, pose
    else:
        return pose
