**For use on internal Allen Institute network**

- fetch configs from ZooKeeper or .yaml/.json file via their path:
```python
test_config: dict = np_config.fetch(
    '/projects/np_logging_test/defaults/logging'
)
```

- the Mindscope ZooKeeper server is at `eng-mindscope:2181`
- configs can be added via ZooNavigator webview:
  [http://eng-mindscope:8081](http://eng-mindscope:8081)
- or more conveniently, via an extension for VSCode such as [gaoliang.visual-zookeeper](https://marketplace.visualstudio.com/items?itemName=gaoliang.visual-zookeeper)

- configs are cached locally: if the ZooKeeper server is unavailable, the local copy will be used