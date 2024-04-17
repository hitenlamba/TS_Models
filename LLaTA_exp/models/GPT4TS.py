# 原版
import numpy as np
import torch
import torch.nn as nn
from torch import optim
import torch.nn.functional as F
from transformers.models.gpt2.modeling_gpt2 import GPT2Model
from transformers import BertTokenizer, BertModel
from einops import rearrange
from transformers.models.gpt2.configuration_gpt2 import GPT2Config
from peft import get_peft_config, get_peft_model, get_peft_model_state_dict, LoraConfig, TaskType
from models.GPT2_arch import AccustumGPT2Model
from models.Attention import MultiHeadAttention
from transformers import AutoTokenizer


from .Embed import DataEmbedding
    
class Encoder_PCA(nn.Module):
    def __init__(self, input_dim, word_embedding, hidden_dim=768, num_heads=12, num_encoder_layers=1):
        super(Encoder_PCA, self).__init__()
        self.linear = nn.Linear(input_dim, hidden_dim)

        encoder_layer = nn.TransformerEncoderLayer(d_model=hidden_dim, nhead=num_heads)
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_encoder_layers)

        self.cross_attention = nn.MultiheadAttention(embed_dim=hidden_dim, num_heads=num_heads)
        
        self.word_embedding = word_embedding.T
        
    def forward(self, x):
        # print('Encoder_PCA')
        B = x.shape[0]
        if self.word_embedding.ndim == 2:
            self.word_embedding = self.word_embedding.repeat(B, 1, 1)
        elif self.word_embedding.shape[0] != B:
            self.word_embedding = self.word_embedding[0].repeat(B, 1, 1)
            
        # print('x1' , x.shape )  ([256, 7, 96]) 
        x = self.linear(x)
        # print('x2' , x.shape ) ([256, 7, 768])

        x = self.transformer_encoder(x.transpose(0, 1)).transpose(0, 1)
        # print('x3' , x.shape ) ([256, 7, 768])

        x_time = x

        q = x.transpose(0, 1)
        k = v = self.word_embedding.transpose(0, 1)
        x, _ = self.cross_attention(q, k, v)

        x = x.transpose(0, 1)
        # print('x4' , x.shape ) ([256, 7, 768]) 
        # print('Encoder_PCA')

        return x_time, x

class Decoder(nn.Module):
    def __init__(self, output_dim, hidden_dim=768, num_heads=12, num_encoder_layers=2):
        super(Decoder, self).__init__()
        self.linear = nn.Linear(hidden_dim, output_dim)

        encoder_layer = nn.TransformerEncoderLayer(d_model=hidden_dim, nhead=num_heads)
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_encoder_layers)

    def forward(self, x):
        x = self.transformer_encoder(x.transpose(0, 1)).transpose(0, 1)
        x = self.linear(x)
        
        return x

class Encoder_Adaptive(nn.Module):
    def __init__(self, input_dim, word_embedding, hidden_dim=768, num_heads=12, num_encoder_layers=1):
        super(Encoder_Adaptive, self).__init__()
        self.register_buffer('word_embedding', word_embedding)
        self.linear = nn.Linear(input_dim, hidden_dim)

        encoder_layer = nn.TransformerEncoderLayer(d_model=hidden_dim, nhead=num_heads)
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_encoder_layers)

        self.dict_proj = nn.Sequential(nn.Linear(768,1000),nn.GELU(),nn.Linear(1000,500))

        self.cross_attention = nn.MultiheadAttention(embed_dim=hidden_dim, num_heads=num_heads)

    def forward(self, x):
        B = x.shape[0]
        word_weight_mat = self.dict_proj(self.word_embedding).transpose(-1,-2)
        word_weight_mat =  torch.softmax(word_weight_mat/0.001,dim=-1)
        #word_weight_mat =  F.gumbel_softmax(word_weight_mat.sigmoid(), tau=0.01, hard=True, dim=-1)
        #word_weight_mat = (word_weight_mat/0.01).sigmoid()/word_weight_mat.shape[-1]
        word_embedding = word_weight_mat@self.word_embedding
        word_embedding = word_embedding.repeat(B,1,1)

        x = self.linear(x)

        x = self.transformer_encoder(x.transpose(0, 1)).transpose(0, 1)

        x_time = x

        q = x.transpose(0, 1)
        k = v = word_embedding.transpose(0, 1)
        x_text, _ = self.cross_attention(q, k, v)

        x_text = x_text.transpose(0, 1)

        return x_time, x_text

class Scale(nn.Module):
    def __init__(self, c):
        super(Scale, self).__init__()
        self.time_scale = nn.Parameter(torch.ones((c, 1)), requires_grad=True)
        self.text_scale = nn.Parameter(torch.ones((c, 1)), requires_grad=True)
        
    def forward(self, x, s):
        if s == 'time':
            return x * self.time_scale
        else:
            return x * self.text_scale

'''

config Namespace(
        task_name='long_term_forecast', is_training=1, model_id='ETTh1_GPT4TS_96_96', 
        model='GPT4TS', data='ETTh1', root_path='./datasets/ETT-small/', data_path='ETTh1.csv', 
        features='M', target='OT', freq='h', checkpoints='./checkpoints/', 
                    
        seq_len=96, label_len=0, pred_len=96, seasonal_patterns='Monthly', inverse=False, 
        mask_rate=0.25, anomaly_ratio=0.25, top_k=5, num_kernels=6, enc_in=7, dec_in=7, c_out=7, 
        d_model=768, n_heads=4, e_layers=2, d_layers=1, d_ff=768, moving_avg=25, factor=1, 
        
        distil=True, dropout=0.3, embed='timeF', activation='gelu', output_attention=False, 
        num_workers=10, itr=3, train_epochs=100, batch_size=256, patience=10, learning_rate=0.0005, 
        des='test', lradj='type1', use_amp=False, task_loss='l1', distill_loss='l1', logits_loss='l1', 
        use_gpu=True, gpu=0, use_multi_gpu=False, devices='0,1,2,3', p_hidden_dims=[128, 128], 
        p_hidden_layers=2, tmax=20, cos=1, r=8, lora_alpha=32, lora_dropout=0.1, word_embedding_path='wte_pca_500.pt', 
        task_w=1.0, feature_w=0.01, logits_w=1.0, gpt_layers=6, percent=100
        )
        
'''
class Model(nn.Module):
    def __init__(self, configs, device):
        super(Model, self).__init__()
        self.pred_len = configs.pred_len
        
        peft_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM, 
            inference_mode=False, 
            r=configs.r,
            lora_alpha=configs.lora_alpha,
            lora_dropout=configs.lora_dropout,
            target_modules=["c_attn"]
        )
        self.n_scale = configs.noise_scale
        self.task_name = configs.task_name
        self.is_first = True 
        self.log_fine_name = configs.log_fine_name
        self.gpt2 = AccustumGPT2Model.from_pretrained('gpt2', output_attentions=True, output_hidden_states=True)  # loads a pretrained GPT-2 base model
        self.gpt2_text = AccustumGPT2Model.from_pretrained('gpt2', output_attentions=True, output_hidden_states=True)  # loads a pretrained GPT-2 base model

        print('config' , configs)
        self.task_type = configs.model_id
        self.gpt2.h = self.gpt2.h[:configs.gpt_layers]
        self.gpt2_text.h = self.gpt2_text.h[:configs.gpt_layers]
        # self.gpt2 = get_peft_model(self.gpt2, peft_config)
        
        word_embedding = torch.tensor(torch.load(configs.word_embedding_path)).to(device=device)
        if 'noise_WE' in self.task_type:
            word_embedding = self.disturb_WE(word_embedding)

        # torch.nn.init.xavier_uniform_(self.linear.weight)
        if 'randomInit' not in self.task_type : 
            for i, (name, param) in enumerate(self.gpt2.named_parameters()):
                if 'ln' in name or 'wpe' in name or 'lora' in name:
                    param.requires_grad = True
                else:
                    param.requires_grad = False
        else :
            
            for i, (name, param) in enumerate(self.gpt2.named_parameters()):
                if 'h.5.attn.c_attn.weight' == name : 
                    print(param)
            del self.gpt2

            self.gpt2  = GPT2Model(GPT2Config())
            self.gpt2.h = self.gpt2.h[:configs.gpt_layers]
            
            for i, (name, param) in enumerate(self.gpt2.named_parameters()):
                if 'h.5.attn.c_attn.weight' == name :  print(param)
                param.requires_grad = True
                
        # import time 
        # time.sleep(200)
        # exit()  
              
        for i, (name, param) in enumerate(self.gpt2_text.named_parameters()):
            if 'wpe' in name:
                param.requires_grad = True
            else:
                param.requires_grad = False

        self.time_proj = nn.ModuleList([nn.Linear(configs.d_model, configs.d_model, bias=False) for _ in range(configs.gpt_layers+1)])
        
        self.text_proj = nn.ModuleList([nn.Linear(configs.d_model, configs.d_model, bias=False) for _ in range(configs.gpt_layers+1)])

        self.in_layer = Encoder_PCA(configs.seq_len, word_embedding, hidden_dim=configs.d_model)
        
        # Attention Part 
        if 'Attn_to_Linear'  in self.task_type:
            self.attn_to_Linear = nn.ModuleList()
            for i in range(7):
                self.attn_to_Linear.append(nn.Linear(768,768))
        if  'Attn_to_Attn'  in self.task_type:
            self.basic_attn =  MultiHeadAttention(d_model =768 )

        # Embedding Part 
        if 'drop_Posi'  in self.task_type:
            self.inject_noise( self.gpt2  , setZero=True)

        if 'noise_Posi' in self.task_type:
            self.inject_noise( self.gpt2  , setZero=False)

        if self.task_name == 'long_term_forecast' or self.task_name == 'short_term_forecast':
            self.out_layer = nn.Linear(configs.d_model, configs.pred_len)
        elif self.task_name == 'classification':
            self.out_layer = nn.Linear(configs.d_model * configs.enc_in, configs.num_class)
        elif self.task_name == 'imputation':
            self.out_layer = nn.Linear(configs.d_model, configs.seq_len)
        elif self.task_name == 'anomaly_detection':
            self.out_layer = nn.Linear(configs.d_model, configs.seq_len)

        for layer in (self.gpt2_text, self.gpt2, self.in_layer, self.out_layer, self.time_proj, self.text_proj):
            layer.to(device=device)
            layer.train()

        self.cnt = 0
        

    def forecast(self, x):
        B, L, M = x.shape

        means = x.mean(1, keepdim=True).detach()
        x = x - means
        stdev = torch.sqrt(torch.var(x, dim=1, keepdim=True, unbiased=False) + 1e-5).detach() 
        x /= stdev
        
        # print('x0' ,x.shape)  torch.Size([256, 96, 7])

        x = rearrange(x, 'b l m -> b m l')
        # print('x1' ,x.shape)  torch.Size([256, 7, 96])
        
        #[256, 7, 768]   [256, 7, 768]
        outputs_time1,  outputs_text1 = self.in_layer(x)

        # GPT2 Attention part : 
        if 'dropAttn_keepWE' in self.task_type :
            outputs_text, _ = self.gpt2_text(inputs_embeds=outputs_text1)
            # residue connection
            outputs_time = outputs_time1
            outputs_text += outputs_text1
            
            # [256, 7, 96] [256, 7, 96]
            outputs_time = self.out_layer(outputs_time[:, -M:, :])
            outputs_text = self.out_layer(outputs_text[:, -M:, :])

            # [256, 96, 7]  [256, 96, 7]
            outputs_time = rearrange(outputs_time, 'b m l -> b l m')
            outputs_text = rearrange(outputs_text, 'b m l -> b l m')
            
            outputs_text = outputs_text * stdev + means
            outputs_time = outputs_time * stdev + means
            
            if self.is_first :
                print('dropAttn_keepWE here !! intermidiate_time is None')
                self.is_first = False 
                
            return {
                'outputs_text': outputs_text,
                'outputs_time':outputs_time,
                'intermidiate_time':None,
                'intermidiate_text':None,
            }
        
        if 'Attn_to_Linear'  in self.task_type:
            outputs_time_channels = torch.zeros([outputs_time1.size(0),outputs_time1.size(1),outputs_time1.size(2)],dtype=outputs_time1.dtype).to(outputs_time1.device)
            for i in range(7):
                outputs_time_channels[:,i,:] = self.attn_to_Linear[i](outputs_time1[:,i,:])

            outputs_text, _ = self.gpt2_text(inputs_embeds=outputs_text1)
            # residue connection
            outputs_time = outputs_time_channels
            # outputs_time += outputs_time_channels
            outputs_text += outputs_text1

            # [256, 7, 96] [256, 7, 96]
            outputs_time = self.out_layer(outputs_time[:, -M:, :])
            outputs_text = self.out_layer(outputs_text[:, -M:, :])

            # [256, 96, 7]  [256, 96, 7]
            outputs_time = rearrange(outputs_time, 'b m l -> b l m')
            outputs_text = rearrange(outputs_text, 'b m l -> b l m')
            
            outputs_text = outputs_text * stdev + means
            outputs_time = outputs_time * stdev + means
            return {
                'outputs_text': outputs_text,
                'outputs_time':outputs_time,
                'intermidiate_time':None,
                'intermidiate_text':None,
            }

        if 'Attn_to_Attn'  in self.task_type:
            outputs_time , _ = self.basic_attn(outputs_time1 , outputs_time1 , outputs_time1 )
            outputs_text, _ = self.gpt2_text(inputs_embeds=outputs_text1)
            outputs_text += outputs_text1

            # [256, 7, 96] [256, 7, 96]
            outputs_time = self.out_layer(outputs_time[:, -M:, :])
            outputs_text = self.out_layer(outputs_text[:, -M:, :])

            # [256, 96, 7]  [256, 96, 7]
            outputs_time = rearrange(outputs_time, 'b m l -> b l m')
            outputs_text = rearrange(outputs_text, 'b m l -> b l m')
            
            outputs_text = outputs_text * stdev + means
            outputs_time = outputs_time * stdev + means
            return {
                'outputs_text': outputs_text,
                'outputs_time':outputs_time,
                'intermidiate_time':None,
                'intermidiate_text':None,
            }

        if 'drop_WE' in self.task_type:
            if self.is_first : print(self.task_type) ; self.is_first = False 
            outputs_time, _ = self.gpt2(inputs_embeds=outputs_time1)
            # residue connection
            outputs_time += outputs_time1

            # [256, 7, 96] [256, 7, 96]
            outputs_time = self.out_layer(outputs_time[:, -M:, :])
            # [256, 96, 7]  [256, 96, 7]
            outputs_time = rearrange(outputs_time, 'b m l -> b l m')
            
            outputs_time = outputs_time * stdev + means
            return {
                'outputs_text': None,
                'outputs_time':outputs_time,
                'intermidiate_time':None,
                'intermidiate_text':None,
            }
        if 'simplest' in self.task_type:
            if self.is_first : print('Orig--' ,self.task_type) ; self.is_first = False 
            outputs_time = outputs_time1
            # [256, 7, 96] [256, 7, 96]
            outputs_time = self.out_layer(outputs_time[:, -M:, :])
            # [256, 96, 7]  [256, 96, 7]
            outputs_time = rearrange(outputs_time, 'b m l -> b l m')
            outputs_time = outputs_time * stdev + means
            return {
                'outputs_text': None,
                'outputs_time':outputs_time,
                'intermidiate_time':None,
                'intermidiate_text':None,
            }
            
        if 'ori' in self.task_type:
            if self.is_first : print('Orig--' ,self.task_type) ; self.is_first = False 
            outputs_time, intermidiate_feat_time = self.gpt2(inputs_embeds=outputs_time1)
            outputs_text, intermidiate_feat_text = self.gpt2_text(inputs_embeds=outputs_text1)
            # residue connection
            outputs_time += outputs_time1
            outputs_text += outputs_text1

            '''
                intermidiate_feat_time
                    0 torch.Size([256, 7, 768])
                    1 torch.Size([256, 7, 768])
                    2 torch.Size([256, 7, 768])
                    3 torch.Size([256, 7, 768])
                    4 torch.Size([256, 7, 768])
                    5 torch.Size([256, 7, 768])
                    6 torch.Size([256, 7, 768])
            '''
            
            intermidiate_feat_time = tuple([self.time_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_time))])
            intermidiate_feat_text = tuple([self.text_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_text))])

            # [256, 7, 96] [256, 7, 96]
            outputs_time = self.out_layer(outputs_time[:, -M:, :])
            outputs_text = self.out_layer(outputs_text[:, -M:, :])

            # [256, 96, 7]  [256, 96, 7]
            outputs_time = rearrange(outputs_time, 'b m l -> b l m')
            outputs_text = rearrange(outputs_text, 'b m l -> b l m')
            
            outputs_text = outputs_text * stdev + means
            outputs_time = outputs_time * stdev + means
            return {
                'outputs_text': outputs_text,
                'outputs_time':outputs_time,
                'intermidiate_time':intermidiate_feat_time,
                'intermidiate_text':intermidiate_feat_text,
            }
        
        if 'randomInit'  in self.task_type :
            if self.is_first : print('randomInit--' ,self.task_type) ; self.is_first = False 
            outputs_time = self.gpt2(inputs_embeds=outputs_time1).last_hidden_state
            # outputs_text, intermidiate_feat_text = self.gpt2_text(inputs_embeds=outputs_text1)
            # residue connection
            outputs_time += outputs_time1
            # outputs_text += outputs_text1

            # intermidiate_feat_time = tuple([self.time_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_time))])
            # intermidiate_feat_text = tuple([self.text_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_text))])

            # [256, 7, 96] [256, 7, 96]
            outputs_time = self.out_layer(outputs_time[:, -M:, :])
            # outputs_text = self.out_layer(outputs_text[:, -M:, :])

            # [256, 96, 7]  [256, 96, 7]
            outputs_time = rearrange(outputs_time, 'b m l -> b l m')
            # outputs_text = rearrange(outputs_text, 'b m l -> b l m')
            
            # outputs_text = outputs_text * stdev + means
            outputs_time = outputs_time * stdev + means
            return {
                'outputs_text': None,
                'outputs_time':outputs_time,
                'intermidiate_time':None,
                'intermidiate_text':None,
            }
    def classification(self, x):
        B, L, M = x.shape

        x = rearrange(x, 'b l m -> b m l')

        outputs_time1, outputs_text1 = self.in_layer(x)
        
        outputs_time, intermidiate_feat_time = self.gpt2(inputs_embeds=outputs_time1)
        outputs_text, intermidiate_feat_text = self.gpt2_text(inputs_embeds=outputs_text1)
        
        outputs_time += outputs_time1
        outputs_text += outputs_text1
        
        intermidiate_feat_time = tuple([self.time_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_time))])
        intermidiate_feat_text = tuple([self.text_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_text))])
        
        outputs_time = outputs_time.reshape(B, -1)
        outputs_text = outputs_text.reshape(B, -1)
        
        outputs_time = self.out_layer(outputs_time)
        outputs_text = self.out_layer(outputs_text)
        
        return {
            'outputs_text': outputs_text,
            'outputs_time':outputs_time,
            'intermidiate_time':intermidiate_feat_time,
            'intermidiate_text':intermidiate_feat_text,
        }

    def imputation(self, x, mask):
        B, L, M = x.shape

        means = x.mean(1, keepdim=True).detach()
        x = x - means
        x = x.masked_fill(mask == 0, 0)

        stdev = torch.sqrt(torch.sum(x**2, dim=1) / torch.sum(mask == 1, dim=1) + 1e-5).unsqueeze(1).detach()
        x /= stdev

        x = rearrange(x, 'b l m -> b m l')

        outputs_time1, outputs_text1 = self.in_layer(x)

        outputs_time, intermidiate_feat_time = self.gpt2(inputs_embeds=outputs_time1)
        outputs_text, intermidiate_feat_text = self.gpt2_text(inputs_embeds=outputs_text1)
        # residue connection
        outputs_time += outputs_time1
        outputs_text += outputs_text1
        
        intermidiate_feat_time = tuple([self.time_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_time))])
        intermidiate_feat_text = tuple([self.text_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_text))])

        outputs_time = self.out_layer(outputs_time)
        outputs_text = self.out_layer(outputs_text)

        outputs_time = rearrange(outputs_time, 'b m l -> b l m')
        outputs_text = rearrange(outputs_text, 'b m l -> b l m')

        outputs_text = outputs_text * stdev + means
        outputs_time = outputs_time * stdev + means

        return {
            'outputs_text': outputs_text,
            'outputs_time':outputs_time,
            'intermidiate_time':intermidiate_feat_time,
            'intermidiate_text':intermidiate_feat_text,
        }

    def anomaly_detection(self, x):
        B, L, M = x.shape

        means = x.mean(1, keepdim=True).detach()
        x = x - means
        stdev = torch.sqrt(torch.var(x, dim=1, keepdim=True, unbiased=False) + 1e-5).detach() 
        x /= stdev

        x = rearrange(x, 'b l m -> b m l')

        outputs_time1, outputs_text1 = self.in_layer(x)

        outputs_time, intermidiate_feat_time = self.gpt2(inputs_embeds=outputs_time1)
        outputs_text, intermidiate_feat_text = self.gpt2_text(inputs_embeds=outputs_text1)
        # residue connection
        outputs_time += outputs_time1
        outputs_text += outputs_text1
        
        intermidiate_feat_time = tuple([self.time_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_time))])
        intermidiate_feat_text = tuple([self.text_proj[idx](feat) for idx, feat in enumerate(list(intermidiate_feat_text))])

        outputs_time = self.out_layer(outputs_time)
        outputs_text = self.out_layer(outputs_text)

        outputs_time = rearrange(outputs_time, 'b m l -> b l m')
        outputs_text = rearrange(outputs_text, 'b m l -> b l m')

        outputs_text = outputs_text * stdev + means
        outputs_time = outputs_time * stdev + means

        return {
            'outputs_text': outputs_text,
            'outputs_time':outputs_time,
            'intermidiate_time':intermidiate_feat_time,
            'intermidiate_text':intermidiate_feat_text,
        }

    def forward(self, x, mask=None):
        if self.task_name == 'long_term_forecast' or self.task_name == 'short_term_forecast':
            output = self.forecast(x)
        if self.task_name == 'classification':
            output = self.classification(x)
        if self.task_name == "imputation":
            output = self.imputation(x, mask)
        if self.task_name == "anomaly_detection":
            output = self.anomaly_detection(x)
        return output

        
    def inject_noise(self  , model , setZero=False ):
        if setZero : 
            # Drop Posi 
            for _, (name, param) in enumerate(model.named_parameters()):
                if 'wpe' in name:  
                    target_wpe_param_ = torch.zeros_like(param).to(device=param.device, dtype=param.dtype)
                    break
        else :
            # Inject Noise to Position 
            with open('results/noise_Posi_96_96/'+self.log_fine_name , 'a') as f:
                f.write('Noise scale to Posi -{}\n'.format(self.n_scale))
                
            for _, (name, param) in enumerate(model.named_parameters()):
                if 'wpe' in name:  
                    noise = torch.randn_like(param).to(device=param.device, dtype=param.dtype) * self.n_scale
                    target_wpe_param_ = param + noise 
                    break

        model.wpe.weight.data = target_wpe_param_.data
        for _, (name, param) in enumerate(model.named_parameters()):
            if 'wpe' in name:  
                print(name, param)
                if setZero : param.requires_grad = False 
                
    def disturb_WE(self , word_embedding):
        noise = torch.randn_like(word_embedding).to(device=word_embedding.device, dtype=word_embedding.dtype) * self.n_scale
        with open('results/noise_WE_96_96/' + self.log_fine_name , 'a') as f :
            f.write('Noise scale to WE -{}\n'.format(self.n_scale))
        return word_embedding + noise 